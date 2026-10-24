"""Load each enabled detector locally (no network) and print health plus the model's own label map.
Run from backend/:  python scripts/verify_models.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyapan.settings")

import django  # noqa: E402

django.setup()

from apps.core.runtime import get_runtime  # noqa: E402

reg = get_runtime().registry
for n in reg.enabled_names():
    d = reg.get(n)
    d.ensure_loaded()
    h = d.health()
    if d.is_available() and hasattr(d, "_model"):
        h["id2label"], h["fake_class_index"] = d._model.config.id2label, d._fake_idx
    print(json.dumps(h, default=str))
