"""Optional OCR corroboration. Only runs when pytesseract AND the Tesseract program are installed; otherwise the state
is "unavailable", which is never treated as suspicious. The image stays in memory."""
import io
import re


def check_image(data: bytes, number: str | None, name: str | None) -> dict:
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        text = pytesseract.image_to_string(img.convert("L"), timeout=15)
    except Exception:  # noqa: BLE001  not installed, not an image (PDF), timeout...
        return {"state": "unavailable"}
    squashed = re.sub(r"[^A-Z0-9]", "", text.upper())
    out: dict = {"state": "checked"}
    if number:
        out["number_found"] = number in squashed
    if name:
        toks = [t for t in re.sub(r"[^A-Z ]", " ", name.upper()).split() if len(t) >= 3]
        out["name_overlap"] = round(sum(t in text.upper() for t in toks) / len(toks), 2) if toks else None
    return out
