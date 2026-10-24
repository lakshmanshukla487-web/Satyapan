"""Network observations of a session: which address the customer connected from, at which moment."""
from pathlib import Path

from apps.biometrics.models import Observation
from apps.core.runtime import get_runtime
from apps.integrity import ipintel


def _dir(cfg) -> str:
    p = Path(cfg.ip_data_dir)
    if p.is_absolute():
        return str(p)
    from satyapan.conf import BASE_DIR
    return str(BASE_DIR / p)


def current_ip(request) -> tuple[str, list[str], dict]:
    cfg = get_runtime().settings
    return ipintel.client_ip_from_meta(request.META, cfg.ip_trusted_proxy_hops)


def observe_ip(request, s, where: str) -> str:
    """Remember the address seen at this step (start, probe, complete): a change during the session is itself a finding."""
    ip, _, _ = current_ip(request)
    Observation.objects.create(session=s, kind="net", data={"ip": ip, "where": where})
    return ip


def earlier_ips(s, current: str) -> list[str]:
    seen = []
    for o in Observation.objects.filter(session=s, kind="net").order_by("created_at"):
        v = o.data.get("ip")
        if v and v != current and v not in seen:
            seen.append(v)
    return seen


def assess_request(request, s, webrtc_ips: list[str]) -> dict | None:
    cfg = get_runtime().settings
    if not cfg.enable_ip_check:
        return None
    ip, notes, hints = current_ip(request)
    parsed = ipintel.parse_ip(ip)
    public = ipintel.address_kind(parsed) == "public"
    reputation = ipintel.reputation_lookup(ip, cfg.ip_reputation_provider, cfg.ip_reputation_api_key) if public else None
    rdns = ipintel.reverse_dns(ip) if (public and cfg.ip_reverse_dns) else None
    net = ipintel.assess(ip_str=ip, header_hints=hints if public else {}, webrtc_ips=webrtc_ips, lists=ipintel.lists_for(_dir(cfg)), reputation=reputation,
                         rdns=rdns, ip_changed_from=earlier_ips(s, ip), notes_in=notes)
    Observation.objects.create(session=s, kind="net", value=net["score"], data={"ip": ip, "where": "probe", "klass": net["klass"], "flags": net["flags"]})
    return net
