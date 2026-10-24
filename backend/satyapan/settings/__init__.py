"""``satyapan.settings`` keeps working as the settings module: base settings first, then the security layer."""
from .base import *  # noqa: F401,F403
from .security import *  # noqa: F401,F403
