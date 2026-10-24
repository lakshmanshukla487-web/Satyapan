"""Pipeline integrity, pure logic: IP intelligence (VPN / proxy / spoofing) and the camera probe (virtual vs hardware)."""
import tempfile
from pathlib import Path

import numpy as np

from apps.integrity import ipintel
from apps.integrity.logic import FLAG_AT, evaluate_probe


# ---------------------------------------------------------------- the customer's address

def test_client_ip_ignores_forwarded_header_unless_proxies_are_trusted():
    meta = {"REMOTE_ADDR": "203.0.113.9", "HTTP_X_FORWARDED_FOR": "198.51.100.7"}
    ip, _, hints = ipintel.client_ip_from_meta(meta, 0)
    assert ip == "203.0.113.9" and "HTTP_X_FORWARDED_FOR" in hints          # anyone can write the header: not believed, but remembered
    ip, notes, hints = ipintel.client_ip_from_meta(meta, 1)
    assert ip == "198.51.100.7" and not hints
    # a client that prepends its own fake entry cannot choose the address: only the entry added by OUR proxy counts
    spoof = {"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "1.2.3.4, 198.51.100.7"}
    assert ipintel.client_ip_from_meta(spoof, 1)[0] == "198.51.100.7"
    ip, notes, _ = ipintel.client_ip_from_meta({"REMOTE_ADDR": "203.0.113.9"}, 2)
    assert ip == "203.0.113.9" and notes


def test_address_kinds():
    k = lambda s: ipintel.address_kind(ipintel.parse_ip(s))  # noqa: E731
    assert k("127.0.0.1") == "loopback" and k("::1") == "loopback"
    assert k("192.168.1.5") == "private" and k("10.1.2.3") == "private"
    assert k("100.64.1.1") == "carrier_nat"
    assert k("8.8.8.8") == "public" and k("[2001:4860:4860::8888]") == "public"
    assert ipintel.address_kind(ipintel.parse_ip("not an ip")) == "invalid"


# ---------------------------------------------------------------- CIDR lists

def _lists(**files) -> ipintel.IpLists:
    d = Path(tempfile.mkdtemp())
    for name, body in files.items():
        (d / name).write_text(body)
    return ipintel.IpLists(str(d))


def test_lists_classify_by_file_name_and_merge_ranges():
    lists = _lists(**{"tor_exit.txt": "185.220.101.0/24\n# comment\n", "vpn_nord.txt": "5.6.7.0/25\n5.6.7.128/25\nnot-a-network\n", "datacenter_aws.txt": "52.0.0.0/11\n2600:1f00::/24\n"})
    ip = ipintel.parse_ip
    assert lists.lookup(ip("185.220.101.44")) == ["tor"]
    assert lists.lookup(ip("5.6.7.200")) == ["vpn"] and lists.lookup(ip("5.6.7.3")) == ["vpn"]
    assert lists.lookup(ip("52.10.10.10")) == ["datacenter"] and lists.lookup(ip("2600:1f18::1")) == ["datacenter"]
    assert lists.lookup(ip("8.8.8.8")) == []
    assert lists.networks == 5 and len(lists.sources) == 3          # the junk line is skipped, not fatal


def test_missing_list_folder_is_empty_not_an_error():
    lists = ipintel.IpLists("/nonexistent/folder")
    assert lists.lookup(ipintel.parse_ip("8.8.8.8")) == [] and lists.sources == []


# ---------------------------------------------------------------- the assessment

def assess(ip="93.184.216.34", **kw):
    base = dict(ip_str=ip, header_hints={}, webrtc_ips=[], lists=None, reputation=None, rdns=None)
    return ipintel.assess(**{**base, **kw})


def test_private_or_loopback_is_not_judged():
    r = assess("127.0.0.1")
    assert r["status"] == "low_quality" and r["score"] is None and r["error_code"] == "IP_NOT_PUBLIC"


def test_clean_address_with_no_source_says_so():
    r = assess()
    assert r["status"] == "ok" and r["score"] == 0.0 and r["klass"] == "clean"
    assert any("No IP reputation list" in n for n in r["notes"])      # an unchecked address is never presented as a verified one


def test_listed_vpn_tor_and_datacenter():
    lists = _lists(**{"vpn_x.txt": "93.184.216.0/24\n", "tor_x.txt": "151.101.1.0/24\n", "hosting.txt": "104.16.0.0/16\n"})
    assert assess("93.184.216.34", lists=lists)["score"] == 0.85 and assess("93.184.216.34", lists=lists)["flags"] == ["vpn"]
    assert assess("151.101.1.5", lists=lists)["score"] == 1.0
    r = assess("104.16.0.5", lists=lists)
    assert r["score"] == 0.65 and r["flags"] == ["datacenter"]


def test_webrtc_leak_flags_a_proxy_that_does_not_cover_everything():
    r = assess(webrtc_ips=["151.101.1.77"])
    assert "webrtc_mismatch" in r["flags"] and r["score"] >= 0.75
    assert "webrtc_mismatch" not in assess(webrtc_ips=["93.184.216.34"])["flags"]            # same address: fine
    assert "webrtc_mismatch" not in assess(webrtc_ips=["2001:4860:4860::8888"])["flags"]   # other IP version: not comparable
    assert "webrtc_mismatch" not in assess(webrtc_ips=["192.168.1.4", "not-an-ip"])["flags"]  # local / garbage addresses are ignored


def test_proxy_headers_and_changed_ip():
    r = assess(header_hints={"HTTP_VIA": "1.1 squid"})
    assert "proxy_headers" in r["flags"] and r["score"] == 0.5
    r = assess(ip_changed_from=["151.101.9.9"])
    assert "ip_changed" in r["flags"] and r["score"] == 0.6 and "151.101.9.9" in " ".join(r["notes"])


def test_reputation_service_results_are_parsed():
    assert ipintel.parse_proxycheck({"status": "ok", "1.2.3.4": {"proxy": "yes", "type": "VPN", "country": "NL"}}, "1.2.3.4")["categories"] == ["vpn"]
    assert ipintel.parse_proxycheck({"status": "ok", "1.2.3.4": {"proxy": "no"}}, "1.2.3.4")["categories"] == []
    assert ipintel.parse_proxycheck({"status": "error"}, "1.2.3.4") == {"ok": False}
    assert ipintel.parse_ipqs({"success": True, "tor": True, "vpn": True, "fraud_score": 90})["categories"] == ["tor", "vpn"]
    assert ipintel.parse_ipqs({"success": False}) == {"ok": False}
    r = assess(reputation={"ok": True, "categories": ["proxy"], "country": "US", "isp": "X", "risk": 80})
    assert r["flags"] == ["proxy"] and r["details"]["reputation_provider_used"] is True


def test_reputation_lookup_without_a_key_is_skipped():
    assert ipintel.reputation_lookup("8.8.8.8", "", "") == {"ok": False, "skipped": True}
    assert ipintel.reputation_lookup("8.8.8.8", "unknown", "k")["ok"] is False


def test_reverse_dns_never_raises():
    assert ipintel.reverse_dns("not-an-ip") is None


# ---------------------------------------------------------------- the camera

def probe(label="", **kw):
    rng = np.random.default_rng(7)
    return {"camera_label": label, "frame_rate": 30, "intervals_ms": list(33.3 + rng.normal(0, 2.5, 100)), **kw}


def test_virtual_camera_names_are_flagged_even_with_natural_timing():
    for name in ("OBS Virtual Camera", "DroidCam Virtual", "ManyCam Virtual Webcam", "Snap Camera", "NDI Video", "Iriun Webcam", "vcam"):
        r = evaluate_probe(probe(name))
        assert r["hard"] and r["score"] >= FLAG_AT and r["klass"] == "virtual" and "virtual_camera" in r["flags"], name


def test_real_hardware_camera_is_not_flagged():
    r = evaluate_probe(probe("Logitech HD Webcam C920 (046d:082d)", capabilities=["focusMode", "exposureMode", "zoom", "brightness"]))
    assert not r["hard"] and r["klass"] == "hardware" and r["score"] == 0.0 and r["metrics"]["usb_vendor"] == "Logitech"
    r = evaluate_probe(probe("Integrated Camera"))
    assert not r["hard"] and r["klass"] == "hardware"


def test_machine_regular_frames_without_hardware_evidence_are_suspected_virtual():
    r = evaluate_probe({"camera_label": "Camera", "frame_rate": 30, "intervals_ms": [33.333] * 100})
    assert r["hard"] and "virtual_camera_suspected" in r["flags"] and r["klass"] == "virtual"
    # the same regular timing on a camera that does show hardware evidence is only a mild signal
    r = evaluate_probe({"camera_label": "Integrated Camera (0bda:5532)", "frame_rate": 30, "intervals_ms": [33.333] * 100})
    assert not r["hard"] and r["score"] < FLAG_AT


def test_patched_browser_api_and_automation_are_flagged():
    r = evaluate_probe(probe("Integrated Camera", native_get_user_media=False))
    assert r["hard"] and "patched_browser_api" in r["flags"] and r["klass"] == "virtual"
    assert evaluate_probe(probe("Integrated Camera", webdriver=True))["hard"]
    r = evaluate_probe(probe("Integrated Camera", video_devices=[{"label": "Integrated Camera"}, {"label": "OBS Virtual Camera"}]))
    assert "virtual_driver_installed" in r["flags"] and not r["hard"] and r["score"] > 0     # installed but not selected: a note-level risk


def test_probe_without_data_is_not_judged_rather_than_trusted():
    r = evaluate_probe({})
    assert r["status"] == "low_quality" and r["score"] is None and r["error_code"] == "NO_PROBE_DATA"
