"""Family 1, pipeline integrity - camera part: is the video coming from a real camera? (framework-free, unit-testable)

The browser sends a probe: camera label (usually with the USB vendor:product id), which controls the camera driver exposes,
the other video devices on the machine, whether getUserMedia was patched by script, and frame-to-frame timings. All of it is
CLIENT-REPORTED. A determined attacker who controls the browser can falsify it, and browsers cannot attest camera hardware, so
this check catches the common, careless attacks (OBS / virtual-camera apps, scripted injection, headless automation) and is
one voice among several, never proof of honesty.

Risk model (0..1): virtual-camera name 0.8, patched getUserMedia 0.6, automation 0.5, unnatural timing 0.25 (+0.3 more when the
camera shows no hardware evidence at all), a virtual driver merely installed 0.25. Real-hardware evidence (USB vendor:product id of
a known manufacturer, driver controls such as focus/exposure, a built-in camera name) lowers it by 0.25 but never cancels a
virtual-camera name, a patched getUserMedia, an automated browser or an installed virtual driver (those claims about hardware cannot be trusted). Flag at 0.5 or more.
"""
import re
import statistics

VIRTUAL_CAMERA = re.compile(
    r"(obs[ -]?(virtual|camera)|virtual|manycam|xsplit|vcam|snap camera|\bndi\b|droidcam|iriun|epoccam|\bcamo\b|splitcam|mmhmm|streamlabs|chromacam|webcamoid|"
    r"unity video capture|e2esoft|webcammax|altercam|cam ?twist|v4l2loopback|loopback|dummy video|fake ?(web)?cam|screen capture|ivcam|vmix|nvidia broadcast|"
    r"logi capture|ecamm|reincubate|youcam|magiccamera|yawcam|virtualcam|wirecast|zoom virtual)", re.I)
VID_PID = re.compile(r"\(([0-9a-f]{4}):([0-9a-f]{4})\)", re.I)
KNOWN_VENDORS = {  # USB vendor ids of common webcam / laptop-camera makers (a vendor:product id means a real USB device answered)
    "046d": "Logitech", "045e": "Microsoft", "04f2": "Chicony", "0bda": "Realtek", "1bcf": "Sunplus", "064e": "Suyin", "041e": "Creative", "1532": "Razer",
    "0fd9": "Elgato", "13d3": "IMC Networks", "174f": "Syntek", "5986": "Acer/Bison", "05ac": "Apple", "04ca": "Lite-On", "0c45": "Microdia", "30c9": "Luxvisions",
    "0408": "Quanta", "04f9": "Brother", "2b7e": "Sunplus-IT", "1b3f": "Generalplus", "0ac8": "Z-Star", "1e4e": "Cubeternet", "0471": "Philips", "046a": "Cherry",
    "093a": "Pixart", "17ef": "Lenovo", "8086": "Intel", "2e1a": "Insta360", "0b05": "ASUS", "04b4": "Cypress", "1415": "Sony-Playstation", "03f0": "HP",
    "0e8d": "MediaTek", "1871": "Aveo", "18ec": "Arkmicro", "1c4f": "SiGma", "1dc3": "Bison", "2560": "Sonix", "0ba6": "Saffron"}
BUILTIN = re.compile(r"(integrated|built-?in|facetime|hd webcam|uvc|usb ?2?\.?0? ?(hd )?(camera|webcam|video)|front camera|back camera|rear camera|camera2 \d+, facing|webcam)", re.I)
HW_CONTROLS = {"focusMode", "focusDistance", "exposureMode", "exposureTime", "exposureCompensation", "whiteBalanceMode", "colorTemperature", "iso", "brightness",
               "contrast", "saturation", "sharpness", "zoom", "pan", "tilt", "torch"}
MIN_INTERVALS = 30
UNIFORM_CV = 0.015   # coefficient of variation of frame intervals below this is unnaturally regular
FPS_TOLERANCE = 0.35  # measured fps more than 35% away from the declared frame rate
FLAG_AT = 0.5


def timing_metrics(intervals: list[float], declared) -> tuple[bool, dict, list[str]]:
    notes, metrics, anomaly = [], {"interval_samples": len(intervals)}, False
    if len(intervals) >= MIN_INTERVALS:
        mean = statistics.fmean(intervals)
        cv = statistics.pstdev(intervals) / mean if mean else 0.0
        fps = 1000.0 / mean if mean else 0.0
        metrics.update({"measured_fps": round(fps, 1), "interval_cv": round(cv, 4)})
        if cv < UNIFORM_CV:
            anomaly = True
            notes.append(f"Frame timing is unnaturally regular (variation {cv:.3f}); real cameras show some jitter.")
        if isinstance(declared, (int, float)) and declared > 0 and abs(fps - declared) / declared > FPS_TOLERANCE:
            anomaly = True
            notes.append(f"Measured frame rate (~{fps:.0f} fps) differs a lot from the declared {declared:.0f} fps.")
    return anomaly, metrics, notes


def evaluate_probe(p: dict) -> dict:
    """-> {status, error_code, hard, score, klass, flags, notes, metrics}. score = camera/browser risk 0..1 (None when nothing could be judged)."""
    label = str(p.get("camera_label") or "").strip()
    intervals = [float(x) for x in (p.get("intervals_ms") or []) if x and x > 0]
    caps = {str(c) for c in (p.get("capabilities") or [])}
    notes: list[str] = []
    flags: list[str] = []
    metrics: dict = {"camera_label_present": bool(label), "capability_count": len(caps & HW_CONTROLS)}

    virtual = VIRTUAL_CAMERA.search(label) if label else None
    m = VID_PID.search(label)
    vendor = KNOWN_VENDORS.get(m.group(1).lower()) if m else None
    hw_controls = len(caps & HW_CONTROLS)
    hardware = bool(vendor) or hw_controls >= 3 or bool(label and BUILTIN.search(label) and not virtual)
    metrics.update({"usb_vendor_product": f"{m.group(1)}:{m.group(2)}".lower() if m else None, "usb_vendor": vendor, "virtual_camera_label": bool(virtual), "hardware_evidence": hardware})

    risk = 0.0
    if virtual:
        risk += 0.8
        flags.append("virtual_camera")
        notes.append(f"The camera name ('{label[:60]}') matches a virtual-camera, screen-capture or phone-as-webcam driver, not a physical camera.")
    anomaly, tm, tnotes = timing_metrics(intervals, p.get("frame_rate"))
    metrics.update(tm)
    metrics["timing_anomaly"] = anomaly
    if anomaly:
        risk += 0.25
        notes += tnotes
        if not hardware and not virtual:
            risk += 0.3
            flags.append("virtual_camera_suspected")
            notes.append("The camera shows no sign of physical hardware (no USB id, no driver controls, no built-in name) and its timing is machine-like.")
    for k, msg in (("native_get_user_media", "The page's camera access function has been replaced by script (getUserMedia is not native). This is how browser-level video injection works."),
                   ("native_enumerate_devices", "The browser's device-listing function has been replaced by script.")):
        if p.get(k) is False:
            risk += 0.6 if k == "native_get_user_media" else 0.3
            flags.append("patched_browser_api")
            notes.append(msg)
    metrics["patched_browser_api"] = "patched_browser_api" in flags
    others = [str(d.get("label", ""))[:80] for d in (p.get("video_devices") or []) if VIRTUAL_CAMERA.search(str(d.get("label", ""))) and str(d.get("label", "")) != label]
    if others and not virtual:
        risk += 0.25
        flags.append("virtual_driver_installed")
        notes.append("A virtual-camera driver is installed on this computer (" + ", ".join(others[:2]) + ") although a different camera is selected.")
    metrics["virtual_devices_listed"] = len(others) + (1 if virtual else 0)
    if p.get("webdriver") is True:
        risk += 0.5
        flags.append("automation")
        notes.append("The browser reports that it is being automated (navigator.webdriver), which is typical of scripted video injection.")
    if hardware and not virtual and not ({"patched_browser_api", "automation", "virtual_driver_installed"} & set(flags)):
        risk -= 0.25
        notes.append("Evidence of a physical camera: " + ", ".join(x for x in ((f"USB id {metrics['usb_vendor_product']} ({vendor})" if vendor else ""), (f"{hw_controls} hardware driver controls" if hw_controls >= 3 else ""),
                                                                              ("built-in camera name" if label and BUILTIN.search(label) else "")) if x) + ".")
    risk = max(0.0, min(1.0, risk))

    if not label and len(intervals) < MIN_INTERVALS and not flags:
        return {"status": "low_quality", "error_code": "NO_PROBE_DATA", "hard": False, "score": None, "klass": "unknown", "flags": flags, "notes": notes, "metrics": metrics}
    klass = "virtual" if (virtual or "virtual_camera_suspected" in flags or "patched_browser_api" in flags) else ("hardware" if hardware else "unknown")
    return {"status": "ok", "error_code": None, "hard": risk >= FLAG_AT, "score": round(risk, 3), "klass": klass, "flags": flags, "notes": notes, "metrics": metrics}
