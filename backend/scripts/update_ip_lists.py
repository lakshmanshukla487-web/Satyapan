"""Download free public IP lists (Tor exit nodes, known VPN ranges, data-centre ranges) into backend/data/ip/.
Run from backend/ on a machine with internet access, and again every few days (add it to cron / Task Scheduler):
    python scripts/update_ip_lists.py
    python scripts/update_ip_lists.py --extra proxy_custom=https://example.org/my-proxy-list.txt
Lists are third-party data: check each source's licence before commercial use. A failed download keeps the previous file."""
import argparse
import ipaddress
import os
import sys
import urllib.request
from pathlib import Path

SOURCES = {
    "tor.txt": "https://check.torproject.org/torbulkexitlist",
    "vpn.txt": "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/vpn/ipv4.txt",
    "datacenter.txt": "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/ipv4.txt",
}

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default=os.getenv("IP_DATA_DIR", "./data/ip"))
ap.add_argument("--extra", action="append", default=[], metavar="NAME=URL", help="add another list; NAME sets the category (tor/vpn/proxy/anything=data centre)")
a = ap.parse_args()
out = Path(a.dir)
out.mkdir(parents=True, exist_ok=True)
sources = dict(SOURCES)
for item in a.extra:
    name, _, url = item.partition("=")
    if not url:
        sys.exit(f"--extra needs NAME=URL, got {item!r}")
    sources[name if name.endswith(".txt") else name + ".txt"] = url

ok = 0
for fname, url in sources.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "satyapan-ip-list-updater"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read(50_000_000).decode("utf-8", "ignore")
        nets = []
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            try:
                nets.append(str(ipaddress.ip_network(line, strict=False)))
            except ValueError:
                continue
        if not nets:
            raise ValueError("no valid networks in the download")
        tmp = out / (fname + ".part")
        tmp.write_text("\n".join(nets) + "\n")
        tmp.replace(out / fname)
        print(f"{fname}: {len(nets)} networks")
        ok += 1
    except Exception as e:  # noqa: BLE001
        print(f"{fname}: FAILED ({type(e).__name__}: {e}); keeping the previous file if there is one", file=sys.stderr)
print(f"Done: {ok}/{len(sources)} lists updated in {out.resolve()}")
sys.exit(0 if ok else 1)
