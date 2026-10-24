from apps.provenance.logic import analyze_bytes
from apps.signals.detector_base import BaseDetector


class ProvenanceDetector(BaseDetector):
    """Family 6. Input: the bytes of an uploaded document. Supporting evidence and notes only; never an indicator."""
    name, signal_type, model_id, score_kind = "provenance", "provenance", None, "rule_based"
    expected = False

    def load(self) -> None:
        pass

    def _infer(self, media, metadata):
        r = analyze_bytes(media)
        notes = []
        if r["editor_software"]:
            notes.append(f"The file metadata names editing software ('{r['editor_software']}'). Many genuine documents are edited (cropped, scanned); this is a note, not an accusation.")
        if r["generator_metadata"]:
            notes.append("The file carries metadata written by an image generator. Ask the customer how this image was produced.")
        details = {"kind": r["kind"], "c2pa_manifest_present": r["c2pa_manifest_marker"], "width": r["width"], "height": r["height"], "notes": notes,
                   "supports": bool(r["c2pa_manifest_marker"] and not r["editor_software"] and not r["generator_metadata"])}
        if r["too_small"]:
            return self.result("low_quality", error_code="DOCUMENT_IMAGE_TOO_SMALL", details=details)
        return self.result("ok", None, label="manifest marker found" if r["c2pa_manifest_marker"] else "no manifest (neutral)", details=details)
