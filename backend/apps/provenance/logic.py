"""Family 6, provenance of an uploaded document image (framework-free, unit-testable).

Opportunistic and POSITIVE-ONLY, as in the submission: a missing Content Credentials manifest means nothing (manifests are
routinely stripped), and a present one is only reported as "present, not validated" because full C2PA validation needs the
c2pa library and a trust list. Editing-software and image-generator metadata are NOTES for the officer, never accusations.
"""
import io
import re

EDITORS = re.compile(r"photoshop|gimp|canva|snapseed|picsart|pixlr|lightroom|paint\.net|affinity|facetune|fotor|capcut|stable diffusion|midjourney|dall[- ]?e|firefly|comfyui", re.I)
GENERATORS = re.compile(r"stable diffusion|midjourney|dall[- ]?e|firefly|comfyui|automatic1111", re.I)
GENERATOR_PNG_KEYS = {"parameters", "prompt", "workflow", "negative_prompt"}  # text chunks written by common image generators
MIN_SIDE_PX = 300


def analyze_bytes(data: bytes) -> dict:
    """Returns {kind, c2pa_manifest_marker, editor_software, generator_metadata, width, height, too_small}."""
    kind = "png" if data.startswith(b"\x89PNG") else "pdf" if data.startswith(b"%PDF-") else "jpeg" if data.startswith(b"\xff\xd8") else "unknown"
    out = {"kind": kind, "c2pa_manifest_marker": (b"c2pa" in data and (b"jumb" in data or b"caBX" in data or b"C2PA" in data)),
           "editor_software": None, "generator_metadata": False, "width": None, "height": None, "too_small": False}
    texts: list[str] = []
    if kind in ("png", "jpeg"):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            out["width"], out["height"] = img.size
            out["too_small"] = min(img.size) < MIN_SIDE_PX
            software = img.getexif().get(305)  # EXIF Software
            if software:
                texts.append(str(software))
            for key, value in (img.info or {}).items():
                if isinstance(value, str):
                    if str(key).lower() in GENERATOR_PNG_KEYS:
                        out["generator_metadata"] = True
                    if str(key).lower() in ("software", "comment", "description", "parameters"):
                        texts.append(value[:400])
        except Exception:  # noqa: BLE001  a damaged image is reported by the size/format checks elsewhere
            pass
    elif kind == "pdf":
        for m in re.finditer(rb"/(Producer|Creator)\s*\(([^)]{0,120})\)", data[:200_000]):
            texts.append(m.group(2).decode("latin-1", "ignore"))
    for t in texts:
        m = EDITORS.search(t)
        if m:
            out["editor_software"] = m.group(0)
            if GENERATORS.search(t):
                out["generator_metadata"] = True
            break
    return out
