"""Authorised local test datasets: sub-folders of DEVLAB_DATASET_DIR (configured by the operator; empty = feature off).

Layout of one dataset (any depth up to 4 folders):
    <DEVLAB_DATASET_DIR>/<dataset>/real/...      files under a folder named real / bonafide / genuine / authentic -> label "real"
    <DEVLAB_DATASET_DIR>/<dataset>/fake/...      files under fake / spoof / deepfake / synthetic / generated     -> label "fake"
    <DEVLAB_DATASET_DIR>/<dataset>/labels.csv    optional "filename,label" lines (relative path or base name); wins over folders
Files without either are tested but unlabelled (excluded from accuracy metrics). Symbolic links are never followed and every
path is re-checked to lie inside the dataset folder, so a dataset cannot point the server at other files."""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from apps.core.errors import AppError
from apps.devlab.media import EXTENSIONS

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
REAL_WORDS = {"real", "bonafide", "bona_fide", "bona-fide", "genuine", "authentic", "live", "original"}
FAKE_WORDS = {"fake", "spoof", "deepfake", "deepfakes", "synthetic", "generated", "manipulated", "attack"}
MAX_DEPTH = 4
MAX_SCAN = 20000


def root(cfg) -> Path | None:
    if not cfg.devlab_dataset_dir:
        return None
    p = Path(cfg.devlab_dataset_dir)
    if not p.is_absolute():
        from satyapan.conf import BASE_DIR
        p = BASE_DIR / p
    return p.resolve() if p.is_dir() else None


def _dataset_dir(cfg, name: str) -> Path:
    base = root(cfg)
    if base is None:
        raise AppError("DATASETS_DISABLED", "No local dataset folder is configured (DEVLAB_DATASET_DIR).", 404)
    if not NAME_RE.match(name or ""):
        raise AppError("DATASET_NOT_FOUND", "Unknown dataset.", 404)
    d = base / name
    if d.is_symlink() or not d.is_dir() or d.resolve().parent != base:
        raise AppError("DATASET_NOT_FOUND", "Unknown dataset.", 404)
    return d.resolve()


def label_from_path(rel: Path) -> str:
    for part in reversed([p.lower() for p in rel.parts[:-1]]):
        if part in REAL_WORDS:
            return "real"
        if part in FAKE_WORDS:
            return "fake"
    return ""


def _csv_labels(d: Path) -> dict[str, str]:
    f = d / "labels.csv"
    if not f.is_file() or f.is_symlink():
        return {}
    out: dict[str, str] = {}
    with f.open(newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            name, lab = row[0].strip().replace("\\", "/"), row[1].strip().lower()
            lab = "real" if lab in REAL_WORDS else "fake" if lab in FAKE_WORDS else ""  # numeric labels are ambiguous: never guessed
            if name and lab and len(out) < MAX_SCAN:
                out[name] = lab
    return out


def scan(cfg, name: str, media_types: set[str] | None = None, limit: int | None = None) -> list[dict]:
    """Files of one dataset: [{rel, media_type, size, label}], sorted by path, at most `limit`."""
    d = _dataset_dir(cfg, name)
    labels = _csv_labels(d)
    out: list[dict] = []
    seen = 0
    for cur, dirs, files in os.walk(d, followlinks=False):
        depth = len(Path(cur).relative_to(d).parts)
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and depth < MAX_DEPTH and not (Path(cur) / x).is_symlink())
        for fn in sorted(files):
            seen += 1
            if seen > MAX_SCAN:
                break
            p = Path(cur) / fn
            media = EXTENSIONS.get(p.suffix.lower())
            if media is None or fn.startswith(".") or p.is_symlink() or (media_types and media not in media_types):
                continue
            rel = p.relative_to(d)
            out.append({"rel": rel.as_posix(), "media_type": media, "size": p.stat().st_size,
                        "label": labels.get(rel.as_posix()) or labels.get(fn) or label_from_path(rel)})
    out.sort(key=lambda x: x["rel"])
    return out[:limit] if limit else out


def resolve_file(cfg, name: str, rel: str) -> Path:
    """The real path of a dataset file, re-validated at processing time (the folder may have changed since the job was made)."""
    d = _dataset_dir(cfg, name)
    p = (d / rel)
    if p.is_symlink():
        raise AppError("INVALID_MEDIA", "Dataset file is a symbolic link.", 422)
    p = p.resolve()
    if d not in p.parents or not p.is_file():
        raise AppError("INVALID_MEDIA", "Dataset file is missing.", 422)
    return p


def list_datasets(cfg) -> dict:
    base = root(cfg)
    if base is None:
        return {"configured": bool(cfg.devlab_dataset_dir), "available": False, "datasets": []}
    items = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.is_symlink() or not NAME_RE.match(d.name):
            continue
        files = scan(cfg, d.name)
        by_media: dict[str, int] = {}
        for f in files:
            by_media[f["media_type"]] = by_media.get(f["media_type"], 0) + 1
        items.append({"name": d.name, "files": len(files), "by_media": by_media, "labelled": sum(1 for f in files if f["label"]),
                      "real": sum(1 for f in files if f["label"] == "real"), "fake": sum(1 for f in files if f["label"] == "fake")})
    return {"configured": True, "available": True, "datasets": items}
