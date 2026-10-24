"""Where is the customer connecting from? VPN / proxy / Tor / data-centre / spoofing checks for the pipeline-integrity family.

Sources, from strongest to weakest (all optional, the report names which ones were used):
  1. CIDR lists in IP_DATA_DIR (one network per line; the file name sets the category: tor*.txt, vpn*.txt, proxy*.txt,
     anything else = data centre / hosting). scripts/update_ip_lists.py downloads free public lists into that folder.
  2. A reputation API (IP_REPUTATION_PROVIDER = proxycheck | ipqs, key in IP_REPUTATION_API_KEY), cached.
  3. WebRTC leak: the browser's own public address (found through STUN) differs from the address this server sees. A full VPN
     changes both; an HTTP proxy or a split-tunnel VPN changes only one.
  4. Proxy headers (Via, Forwarded, X-Forwarded-For) that arrive although no trusted proxy is configured.
  5. IP changing during the session.
Honest limits: a residential proxy, a fresh VPN address and a VPN that is not on any list look like a normal home connection.
No IP check proves a person is honest; it is evidence to be weighed with the others.
"""
from __future__ import annotations

import bisect
import ipaddress
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("satyapan.ip")

CATEGORY_RISK = {"tor": 1.0, "vpn": 0.85, "proxy": 0.85, "datacenter": 0.65}
CATEGORY_LABEL = {"tor": "the Tor network", "vpn": "a VPN service", "proxy": "an anonymising proxy", "datacenter": "a data centre / hosting provider"}


# ---- address helpers ------------------------------------------------------------------------------------------------------

def parse_ip(s: str):
    try:
        return ipaddress.ip_address(str(s).strip().strip("[]"))
    except ValueError:
        return None


def is_public(ip) -> bool:
    return bool(ip) and ip.is_global and not ip.is_multicast


def address_kind(ip) -> str:
    if ip is None:
        return "invalid"
    if ip.is_loopback:
        return "loopback"
    if ip.is_private or ip.is_link_local:
        return "private"
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "carrier_nat"
    return "public" if ip.is_global else "reserved"


def client_ip_from_meta(meta: dict, trusted_hops: int) -> tuple[str, list[str], dict]:
    """The customer's address. With TRUSTED_PROXY_HOPS = n, the n right-most entries of X-Forwarded-For were added by our own
    proxies, so the entry before them is the client. With 0 the header is ignored (anyone can write it)."""
    remote = (meta.get("REMOTE_ADDR") or "").strip()
    xff = [x.strip() for x in (meta.get("HTTP_X_FORWARDED_FOR") or "").split(",") if x.strip()]
    notes: list[str] = []
    headers = {k: meta.get(k) for k in ("HTTP_VIA", "HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_PROXY_CONNECTION") if meta.get(k)}
    if trusted_hops > 0:
        chain = xff + [remote]
        if len(chain) > trusted_hops:
            return chain[-(trusted_hops + 1)], notes, {}
        notes.append("Fewer forwarded addresses than trusted proxies were configured; using the connecting address.")
        return remote, notes, {}
    return remote, notes, headers


# ---- CIDR lists ------------------------------------------------------------------------------------------------------------

def _category_for(filename: str) -> str:
    n = filename.lower()
    for key, cat in (("tor", "tor"), ("vpn", "vpn"), ("proxy", "proxy")):
        if key in n:
            return cat
    return "datacenter"


class IpLists:
    """Merged CIDR ranges per (category, IP version), reloaded when a file changes (checked at most once a minute)."""

    def __init__(self, data_dir: str):
        self.dir = Path(data_dir)
        self._sig: tuple = ()
        self._checked = 0.0
        self._lock = threading.Lock()
        self._idx: dict[tuple[str, int], tuple[list[int], list[int]]] = {}
        self.sources: list[str] = []
        self.networks = 0

    def _signature(self) -> tuple:
        if not self.dir.is_dir():
            return ()
        return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(self.dir.glob("*.txt")))

    def reload_if_needed(self) -> None:
        now = time.monotonic()
        if now - self._checked < 60 and self._sig is not None and self._idx is not None and self._checked:
            return
        with self._lock:
            self._checked = now
            sig = self._signature()
            if sig == self._sig and self._checked:
                return
            ranges: dict[tuple[str, int], list[tuple[int, int]]] = {}
            n, sources = 0, []
            for p in sorted(self.dir.glob("*.txt")) if self.dir.is_dir() else []:
                cat, count = _category_for(p.name), 0
                try:
                    for line in p.read_text(errors="ignore").splitlines():
                        line = line.split("#")[0].strip()
                        if not line:
                            continue
                        try:
                            net = ipaddress.ip_network(line, strict=False)
                        except ValueError:
                            continue
                        ranges.setdefault((cat, net.version), []).append((int(net.network_address), int(net.broadcast_address)))
                        count += 1
                except OSError:
                    continue
                n += count
                if count:
                    sources.append(f"{p.name} ({count})")
            idx = {}
            for key, rs in ranges.items():
                rs.sort()
                merged: list[list[int]] = []
                for a, b in rs:
                    if merged and a <= merged[-1][1] + 1:
                        merged[-1][1] = max(merged[-1][1], b)
                    else:
                        merged.append([a, b])
                idx[key] = ([m[0] for m in merged], [m[1] for m in merged])
            self._idx, self._sig, self.sources, self.networks = idx, sig, sources, n

    def lookup(self, ip) -> list[str]:
        self.reload_if_needed()
        out = []
        v = int(ip)
        for (cat, ver), (starts, ends) in self._idx.items():
            if ver != ip.version:
                continue
            i = bisect.bisect_right(starts, v) - 1
            if i >= 0 and v <= ends[i]:
                out.append(cat)
        return sorted(set(out), key=lambda c: -CATEGORY_RISK[c])


_lists: dict[str, IpLists] = {}


def lists_for(data_dir: str) -> IpLists:
    if data_dir not in _lists:
        _lists[data_dir] = IpLists(data_dir)
    return _lists[data_dir]


# ---- reputation API (optional) ----------------------------------------------------------------------------------------------

def parse_proxycheck(payload: dict, ip: str) -> dict:
    """proxycheck.io v2: {"status":"ok","<ip>":{"proxy":"yes","type":"VPN","provider":..,"country":..,"risk":..}}"""
    if payload.get("status") not in ("ok", "warning"):
        return {"ok": False}
    d = payload.get(ip) or {}
    typ = str(d.get("type") or "").lower()
    cats = []
    if str(d.get("proxy")).lower() == "yes":
        cats.append("tor" if "tor" in typ else "vpn" if "vpn" in typ else "datacenter" if typ in ("hosting", "compromised server") else "proxy")
    return {"ok": True, "categories": cats, "country": d.get("country"), "isp": d.get("provider"), "risk": d.get("risk")}


def parse_ipqs(payload: dict) -> dict:
    """IPQualityScore: {"success":true,"proxy":..,"vpn":..,"tor":..,"active_vpn":..,"active_tor":..,"fraud_score":..,"country_code":..,"ISP":..}"""
    if not payload.get("success"):
        return {"ok": False}
    cats = []
    if payload.get("tor") or payload.get("active_tor"):
        cats.append("tor")
    if payload.get("vpn") or payload.get("active_vpn"):
        cats.append("vpn")
    if payload.get("proxy"):
        cats.append("proxy")
    return {"ok": True, "categories": cats, "country": payload.get("country_code"), "isp": payload.get("ISP"), "risk": payload.get("fraud_score")}


def reputation_lookup(ip: str, provider: str, key: str, timeout: float = 2.0) -> dict:
    if not provider or not key:
        return {"ok": False, "skipped": True}
    url = {"proxycheck": f"https://proxycheck.io/v2/{ip}?key={key}&vpn=1&asn=1&risk=1", "ipqs": f"https://ipqualityscore.com/api/json/ip/{key}/{ip}"}.get(provider)
    if url is None:
        return {"ok": False, "skipped": True}
    from apps.core.cache import cache_get, cache_set
    ck = f"ipq:{provider}:{ip}"
    hit = cache_get(ck)
    if hit is not None:
        return hit
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "satyapan/1"}), timeout=timeout) as r:
            payload = json.loads(r.read(200_000).decode("utf-8", "ignore"))
        res = parse_proxycheck(payload, ip) if provider == "proxycheck" else parse_ipqs(payload)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("ip reputation lookup failed: %s", type(e).__name__)
        return {"ok": False, "error": type(e).__name__}
    cache_set(ck, res, 3600)
    return res


HOST_HINTS = ("vpn", "proxy", "tor-exit", "exit-node", "amazonaws.com", "googleusercontent.com", "compute", "hosting", "vps", "cloud", "server", "datacenter", "digitalocean", "linode", "ovh", "hetzner", "m247", "choopa")


_rdns_pool = None


def reverse_dns(ip: str, timeout: float = 1.5) -> str | None:
    """Host name of the address, or None. gethostbyaddr ignores socket timeouts, so it runs in a small worker pool and the
    request only waits `timeout` seconds for it (a slow resolver can never hold a request up)."""
    global _rdns_pool
    import socket
    from concurrent.futures import ThreadPoolExecutor
    if _rdns_pool is None:
        _rdns_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rdns")
    try:
        return _rdns_pool.submit(socket.gethostbyaddr, ip).result(timeout)[0].lower()
    except Exception:  # timeout, no PTR record, bad address: all mean "unknown"
        return None


# ---- the assessment --------------------------------------------------------------------------------------------------------

def assess(*, ip_str: str, header_hints: dict, webrtc_ips: list[str], lists: IpLists | None, reputation: dict | None, rdns: str | None,
           ip_changed_from: list[str] | None = None, notes_in: list[str] | None = None) -> dict:
    """-> {status, score, klass, flags[], notes[], details}. score 0..1 (risk). status low_quality when nothing could be judged."""
    notes: list[str] = list(notes_in or [])
    flags: list[str] = []
    ip = parse_ip(ip_str)
    kind = address_kind(ip)
    details: dict = {"ip": ip_str if ip else None, "address_kind": kind, "list_sources": lists.sources if lists else [], "reputation_provider_used": bool(reputation and reputation.get("ok"))}
    if kind in ("loopback", "private", "carrier_nat", "reserved", "invalid"):
        why = {"loopback": "this computer itself", "private": "a private network", "carrier_nat": "a mobile-carrier shared address", "reserved": "a reserved address", "invalid": "an unreadable address"}[kind]
        notes.append(f"The server sees the connection as coming from {why}, so the public address could not be checked. "
                     "This is normal when testing on one computer or behind an unconfigured reverse proxy.")
        return {"status": "low_quality", "error_code": "IP_NOT_PUBLIC", "score": None, "klass": "not_public", "flags": flags, "notes": notes, "details": details}
    cats: list[str] = lists.lookup(ip) if lists else []
    if reputation and reputation.get("ok"):
        cats = sorted(set(cats) | set(reputation.get("categories", [])), key=lambda c: -CATEGORY_RISK[c])
        details.update(country=reputation.get("country"), isp=reputation.get("isp"), provider_risk=reputation.get("risk"))
    if rdns:
        details["reverse_dns"] = rdns
        if any(h in rdns for h in HOST_HINTS) and "datacenter" not in cats and not cats:
            cats.append("datacenter")
            notes.append(f"The address's host name ({rdns[:60]}) looks like a hosting or VPN provider.")
    score = 0.0
    for c in cats:
        score = max(score, CATEGORY_RISK[c])
        flags.append(c)
        notes.append(f"The connection comes from {CATEGORY_LABEL[c]}.")
    # WebRTC leak: compare addresses of the same IP version
    leaks = []
    for w in webrtc_ips or []:
        wip = parse_ip(w)
        if wip is not None and is_public(wip) and wip.version == ip.version and wip != ip:
            leaks.append(str(wip))
    if leaks:
        flags.append("webrtc_mismatch")
        score = max(score, 0.75)
        details["webrtc_public_ips"] = leaks[:4]
        notes.append(f"The browser's own public address ({leaks[0]}) differs from the address the server sees ({ip_str}): the web traffic is going through a proxy or VPN that does not cover everything.")
    elif webrtc_ips:
        details["webrtc_checked"] = True
    if header_hints:
        flags.append("proxy_headers")
        score = max(score, 0.5)
        details["proxy_headers"] = sorted(k.replace("HTTP_", "").lower() for k in header_hints)
        notes.append("The request carries proxy headers (" + ", ".join(details["proxy_headers"]) + ") although no trusted proxy is configured: a forwarding proxy sits in between.")
    if ip_changed_from:
        flags.append("ip_changed")
        score = max(score, 0.6)
        details["earlier_ips"] = ip_changed_from[:4]
        notes.append("The customer's IP address changed during the session (earlier: " + ", ".join(ip_changed_from[:3]) + ").")
    have_source = bool(lists and lists.sources) or bool(reputation and reputation.get("ok"))
    details["reputation_sources_available"] = have_source
    if not have_source and not flags:
        notes.append("No IP reputation list or service is configured, so VPN/proxy detection relied on the WebRTC and header checks only.")
    klass = flags[0] if flags else "clean"
    return {"status": "ok", "error_code": None, "score": round(score, 3), "klass": klass, "flags": flags, "notes": notes, "details": details}
