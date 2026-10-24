"""Evaluation metrics for a labelled test job. Pure functions (unit-testable without a database).

Positive class = "fake". A sample takes part only when it has a ground-truth label AND the real detector produced a score and a
prediction; every other sample is counted under `excluded` with the reason, so nothing is silently dropped. Metrics that are
undefined for the data (for example precision when nothing was predicted fake, or ROC AUC with only one class present) are
returned as null with a note instead of a made-up number."""
from __future__ import annotations

from collections import Counter

EXCLUDE_REASONS = {
    "unlabelled": "no ground-truth label",
    "unavailable": "detector unavailable (model or weights missing)",
    "error": "decoding or inference error",
    "low_quality": "input too poor to score (same rule as the live pipeline)",
    "cancelled": "job cancelled before this sample ran",
    "pending": "not processed yet",
}


def _div(a: float, b: float):
    return round(a / b, 4) if b else None


def roc_auc(pairs: list[tuple[float, int]]) -> float | None:
    """Area under the ROC curve from (score, is_fake) pairs (Mann-Whitney U with tie correction). None if one class is absent."""
    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    ranked = sorted(pairs, key=lambda p: p[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-based average rank of the tie group
        rank_sum += avg_rank * sum(1 for k in range(i, j + 1) if ranked[k][1])
        i = j + 1
    u = rank_sum - pos * (pos + 1) / 2
    return round(u / (pos * neg), 4)


def _bucket(item: dict) -> str | None:
    """None = takes part in the metrics; otherwise the exclusion reason key."""
    st = item["status"]
    if st in ("queued", "running"):
        return "pending"
    if st != "done":
        return st if st in EXCLUDE_REASONS else "error"
    if item.get("label") not in ("real", "fake"):
        return "unlabelled"
    if item.get("prediction") not in ("real", "fake") or item.get("score") is None:
        return "error"
    return None


def evaluate(items: list[dict]) -> list[dict]:
    """One metrics block per (media type, detector) group. items: dicts with status, label, prediction, score, threshold,
    media_type, detector."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        groups.setdefault((it["media_type"], it.get("detector") or "-"), []).append(it)
    return [_evaluate_group(media, det, rows) for (media, det), rows in sorted(groups.items())]


def _evaluate_group(media: str, detector: str, rows: list[dict]) -> dict:
    excluded = Counter()
    used = []
    for it in rows:
        b = _bucket(it)
        if b is None:
            used.append(it)
        else:
            excluded[b] += 1
    labelled = [it for it in rows if it.get("label") in ("real", "fake")]
    out = {"media_type": media, "detector": detector, "samples": len(rows), "labelled": len(labelled), "evaluated": len(used),
           "excluded": [{"reason": k, "text": EXCLUDE_REASONS[k], "count": v} for k, v in sorted(excluded.items())],
           "thresholds": sorted({it["threshold"] for it in used if it.get("threshold") is not None}),
           "class_support": {"real": sum(1 for it in labelled if it["label"] == "real"), "fake": sum(1 for it in labelled if it["label"] == "fake")},
           "available": False, "notes": []}
    if not labelled:
        out["notes"].append("No ground-truth labels were provided, so no accuracy or other benchmark metric can be reported.")
        return out
    if not used:
        out["notes"].append("No labelled sample produced a usable detector result, so no metric can be reported.")
        return out
    tp = sum(1 for it in used if it["label"] == "fake" and it["prediction"] == "fake")
    fn = sum(1 for it in used if it["label"] == "fake" and it["prediction"] == "real")
    tn = sum(1 for it in used if it["label"] == "real" and it["prediction"] == "real")
    fp = sum(1 for it in used if it["label"] == "real" and it["prediction"] == "fake")
    n = tp + tn + fp + fn
    precision, recall = _div(tp, tp + fp), _div(tp, tp + fn)
    specificity = _div(tn, tn + fp)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision is not None and recall is not None and (precision + recall) > 0 else None
    balanced = round((recall + specificity) / 2, 4) if recall is not None and specificity is not None else None
    evaluated_support = {"real": tn + fp, "fake": tp + fn}
    out.update(available=True, confusion_matrix={"labels": ["real", "fake"], "rows_are": "ground truth", "columns_are": "prediction",
                                                 "matrix": [[tn, fp], [fn, tp]]},
               true_positive=tp, false_positive=fp, true_negative=tn, false_negative=fn,
               accuracy=_div(tp + tn, n), precision=precision, recall=recall, specificity=specificity, f1=f1, balanced_accuracy=balanced,
               roc_auc=roc_auc([(it["score"], 1 if it["label"] == "fake" else 0) for it in used]), evaluated_support=evaluated_support)
    if evaluated_support["real"] == 0 or evaluated_support["fake"] == 0:
        out["notes"].append("Only one class is present among the evaluated samples: specificity or recall, balanced accuracy and ROC AUC are undefined.")
    elif max(evaluated_support.values()) >= 3 * min(evaluated_support.values()):
        out["notes"].append("The classes are strongly imbalanced: read balanced accuracy, F1 and ROC AUC rather than plain accuracy.")
    if precision is None:
        out["notes"].append("Nothing was predicted fake, so precision is undefined.")
    if excluded:
        out["notes"].append(f"{sum(excluded.values())} sample(s) were excluded (see the reasons); the metrics cover the {n} evaluated sample(s) only.")
    out["notes"].append("Predictions compare an uncalibrated model score with the configured demo threshold; these numbers describe this dataset only.")
    return out


def summary(items: list[dict]) -> dict:
    """Dataset-level counts that need no labels."""
    by_status = Counter(it["status"] for it in items)
    by_media = {}
    for media in sorted({it["media_type"] for it in items}):
        rows = [it for it in items if it["media_type"] == media]
        scores = [it["score"] for it in rows if it.get("score") is not None]
        by_media[media] = {"count": len(rows), "scored": len(scores), "predicted_fake": sum(1 for it in rows if it.get("prediction") == "fake"),
                           "predicted_real": sum(1 for it in rows if it.get("prediction") == "real"),
                           "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
                           "mean_duration_ms": round(sum(it["duration_ms"] for it in rows if it.get("duration_ms") is not None) /
                                                     max(1, sum(1 for it in rows if it.get("duration_ms") is not None)), 1) if any(it.get("duration_ms") is not None for it in rows) else None}
    done = sum(by_status.get(k, 0) for k in ("done", "low_quality", "unavailable", "error", "cancelled"))
    return {"total": len(items), "finished": done, "by_status": dict(by_status), "by_media": by_media}
