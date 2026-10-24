from apps.core.errors import AppError
from apps.core.validation import read_limited


def read_upload(request, max_mb: int) -> bytes:
    """The single `file` part of a multipart request, size-checked."""
    f = request.FILES.get("file")
    if f is None:
        # A body far over the limit is skipped by the in-memory upload handler instead of being stored.
        if int(request.META.get("CONTENT_LENGTH") or 0) > (max_mb + 1) * 1024 * 1024:
            raise AppError("FILE_TOO_LARGE", f"Upload exceeds the {max_mb} MB limit.", 413)
        raise AppError("VALIDATION_ERROR", "The request was invalid.", 422)
    return read_limited(f, max_mb)
