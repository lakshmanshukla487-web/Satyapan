from apps.core.errors import AppError

AUDIO_MAGIC = (b"RIFF", b"fLaC", b"OggS")
IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
PDF_MAGIC = (b"%PDF-",)


def read_limited(file, max_mb: int) -> bytes:
    """Read an uploaded file (held in memory by the upload handler), enforcing the size limit."""
    limit = max_mb * 1024 * 1024
    data = file.read(limit + 1)
    if len(data) > limit:
        raise AppError("FILE_TOO_LARGE", f"Upload exceeds the {max_mb} MB limit.", 413)
    if not data:
        raise AppError("EMPTY_UPLOAD", "The uploaded file is empty.", 422)
    return data


def sniff(data: bytes, kind: str) -> None:
    """Check file content (not filename or MIME type) before decoding. kind: audio | image | document (image or PDF)."""
    magics = {"audio": AUDIO_MAGIC, "image": IMAGE_MAGIC, "document": IMAGE_MAGIC + PDF_MAGIC}[kind]
    if not data.startswith(magics):
        allowed = {"audio": "WAV, FLAC, OGG.", "image": "JPEG, PNG.", "document": "JPEG, PNG, PDF."}[kind]
        raise AppError("UNSUPPORTED_MEDIA", f"Unsupported {kind} format. Supported: {allowed}", 415)


def sniff_kind(data: bytes) -> str:
    """jpeg | png | pdf (after sniff(data, "document") has passed)."""
    return "png" if data.startswith(IMAGE_MAGIC[0]) else "pdf" if data.startswith(PDF_MAGIC) else "jpeg"
