"""Untrusted test media: identification by CONTENT (never by the client's MIME type), limits, and decoding for the detectors.

Images and WAV/FLAC/OGG audio are decoded with the same helpers as the live pipeline (apps/core/media.py), so a test sees
exactly the preprocessing a live sample gets. Video is decoded with OpenCV (installed with the ML requirements) and sampled
evenly. MP3/M4A audio is converted with the ffmpeg program when it is installed (reported as unsupported otherwise)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from apps.core.errors import AppError

IMAGE, AUDIO, VIDEO = "image", "audio", "video"
EXTENSIONS = {
    ".jpg": IMAGE, ".jpeg": IMAGE, ".png": IMAGE,
    ".wav": AUDIO, ".flac": AUDIO, ".ogg": AUDIO, ".mp3": AUDIO, ".m4a": AUDIO,
    ".mp4": VIDEO, ".m4v": VIDEO, ".mov": VIDEO, ".webm": VIDEO, ".mkv": VIDEO, ".avi": VIDEO,
}
MEDIA_OF = {"jpeg": IMAGE, "png": IMAGE, "wav": AUDIO, "flac": AUDIO, "ogg": AUDIO, "mp3": AUDIO, "m4a": AUDIO,
            "mp4": VIDEO, "mov": VIDEO, "webm": VIDEO, "avi": VIDEO}
NEEDS_FFMPEG = {"mp3", "m4a"}
MAX_FRAMES_CAP = 64
FFMPEG_TIMEOUT_S = 60


def sniff_format(head: bytes) -> str | None:
    """File format from its first bytes. None = not a supported format."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"OggS"):
        return "ogg"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        return "mov" if brand == b"qt  " else "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"  # Matroska / WebM
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def safe_filename(name: str) -> str:
    """Display name only (never used as a path): the base name, without control characters, at most 200 characters."""
    base = Path(str(name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>"')
    return (base or "unnamed")[:200]


def identify(filename: str, head: bytes) -> tuple[str, str]:
    """-> (media_type, file_format). The extension must agree with the content; the content decides."""
    fmt = sniff_format(head)
    if fmt is None:
        raise AppError("UNSUPPORTED_MEDIA", "Unsupported file. Images: JPEG, PNG. Audio: WAV, FLAC, OGG (MP3, M4A with ffmpeg). Video: MP4, MOV, WebM, MKV, AVI.", 415)
    media = MEDIA_OF[fmt]
    ext_media = EXTENSIONS.get(Path(filename).suffix.lower())
    if ext_media is not None and ext_media != media:
        raise AppError("MEDIA_TYPE_MISMATCH", f"The file content is {fmt.upper()} ({media}), which does not match its extension.", 415)
    return media, fmt


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


# ---- probing (at upload time: reject what can never be analysed, before the job starts) ------------------------------------

def probe(path: Path, media: str, fmt: str, cfg) -> dict:
    """Cheap validity check. -> {duration_s?, width?, height?, frames?, fps?}. Raises AppError for unusable files."""
    if media == IMAGE:
        from PIL import Image
        try:
            with Image.open(path) as im:
                w, h = im.size
        except Exception:
            raise AppError("INVALID_MEDIA", "The image could not be read.", 422)
        if max(w, h) > cfg.max_image_dimension:
            raise AppError("IMAGE_TOO_LARGE", f"Image dimensions exceed {cfg.max_image_dimension}px.", 422)
        return {"width": w, "height": h}
    if media == AUDIO:
        if fmt in NEEDS_FFMPEG:
            if ffmpeg_path() is None:
                raise AppError("CODEC_UNAVAILABLE", f"{fmt.upper()} audio needs the ffmpeg program on the server. Convert to WAV or FLAC, or install ffmpeg.", 422)
            return {}
        import soundfile as sf
        try:
            info = sf.info(str(path))
        except Exception:
            raise AppError("INVALID_MEDIA", "The audio could not be decoded.", 422)
        if info.duration > cfg.devlab_max_audio_seconds:
            raise AppError("AUDIO_TOO_LONG", f"Audio exceeds the {cfg.devlab_max_audio_seconds} s test limit.", 422)
        return {"duration_s": round(float(info.duration), 2), "sample_rate": int(info.samplerate)}
    meta = _video_meta(path)
    if meta["duration_s"] is not None and meta["duration_s"] > cfg.devlab_max_video_seconds:
        raise AppError("VIDEO_TOO_LONG", f"Video exceeds the {cfg.devlab_max_video_seconds} s test limit.", 422)
    if max(meta["width"], meta["height"]) > cfg.max_image_dimension:
        raise AppError("IMAGE_TOO_LARGE", f"Video frame dimensions exceed {cfg.max_image_dimension}px.", 422)
    return meta


def _video_meta(path: Path) -> dict:
    try:
        import cv2
    except ImportError:
        raise AppError("DEPENDENCY_MISSING", "Video testing needs OpenCV (pip install -r requirements-ml.txt).", 422)
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise AppError("INVALID_MEDIA", "The video could not be opened.", 422)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w <= 0 or h <= 0:
            ok, frame = cap.read()
            if not ok or frame is None:
                raise AppError("INVALID_MEDIA", "The video contains no readable frames.", 422)
            h, w = frame.shape[:2]
        valid = 0 < fps <= 240 and n > 0
        return {"fps": round(fps, 3) if valid else None, "frames": n if valid else None, "duration_s": round(n / fps, 2) if valid else None, "width": w, "height": h}
    finally:
        cap.release()


# ---- decoding for the detectors -----------------------------------------------------------------------------------------------

def load_audio(path: Path, fmt: str, max_seconds: int) -> tuple[np.ndarray, int]:
    """Mono float32 waveform + sample rate, through the live pipeline's decoder (WAV/FLAC/OGG) or ffmpeg (MP3/M4A)."""
    from apps.core.media import decode_audio
    if fmt in NEEDS_FFMPEG:
        exe = ffmpeg_path()
        if exe is None:
            raise AppError("CODEC_UNAVAILABLE", f"{fmt.upper()} audio needs the ffmpeg program on the server.", 422)
        # No shell; input is a server-chosen path; output bounded to max_seconds + 1 s so an over-long file is detected cheaply.
        proc = subprocess.run([exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", str(max_seconds + 1),
                               "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"], capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
        if proc.returncode != 0 or not proc.stdout:
            raise AppError("INVALID_MEDIA", "The audio could not be decoded.", 422)
        return decode_audio(proc.stdout, max_seconds)
    return decode_audio(path.read_bytes(), max_seconds)


def sample_video_frames(path: Path, count: int, max_seconds: int, max_dim: int, should_stop=lambda: False) -> tuple[list, dict]:
    """`count` RGB frames spread evenly over the whole video (first to last frame). Frames are reached by grab() (no decoding)
    and only the chosen ones are decoded, so the work is bounded by the video length limit. -> (frames, info)."""
    import cv2
    count = max(1, min(MAX_FRAMES_CAP, int(count)))
    meta = _video_meta(path)
    fps = meta["fps"] or 30.0
    hard_cap = int(max_seconds * min(fps, 240) + fps)  # never read more frames than the duration limit allows
    total = meta["frames"]
    if total is None:  # container without a reliable frame count: count by grabbing (bounded)
        cap = cv2.VideoCapture(str(path))
        total = 0
        try:
            while total <= hard_cap and cap.grab():
                total += 1
                if total % 500 == 0 and should_stop():
                    break
        finally:
            cap.release()
        if total > hard_cap:
            raise AppError("VIDEO_TOO_LONG", f"Video exceeds the {max_seconds} s test limit.", 422)
    if total <= 0:
        raise AppError("INVALID_MEDIA", "The video contains no readable frames.", 422)
    targets = sorted(set(int(round(x)) for x in np.linspace(0, total - 1, num=min(count, total))))
    frames, idx, ti = [], 0, 0
    cap = cv2.VideoCapture(str(path))
    try:
        while ti < len(targets) and idx <= min(total, hard_cap):
            if not cap.grab():
                break
            if idx == targets[ti]:
                ok, bgr = cap.retrieve()
                if ok and bgr is not None:
                    h, w = bgr.shape[:2]
                    if max(h, w) > max_dim:
                        raise AppError("IMAGE_TOO_LARGE", f"Video frame dimensions exceed {max_dim}px.", 422)
                    frames.append({"index": idx, "time_s": round(idx / fps, 3), "rgb": cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)})
                ti += 1
            idx += 1
            if idx % 500 == 0 and should_stop():
                break
    finally:
        cap.release()
    if not frames:
        raise AppError("INVALID_MEDIA", "No frame of the video could be decoded.", 422)
    return frames, {"total_frames": total, "fps": meta["fps"], "duration_s": meta["duration_s"] or round(total / fps, 2), "width": meta["width"], "height": meta["height"],
                    "requested_frames": count, "sampled_frames": len(frames)}


def image_from_bytes(data: bytes, max_dim: int):
    from apps.core.media import decode_image
    return decode_image(data, max_dim)


def to_pil(rgb: np.ndarray):
    from PIL import Image
    return Image.fromarray(np.ascontiguousarray(rgb))

