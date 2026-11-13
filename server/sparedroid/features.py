"""Feature switches, mirrored on the phone (Features.kt).

A feature must be on in **both** places to work: the server refuses to queue it, and the phone refuses
to run it. Listening to notifications is not a feature switch; the app allow-list controls that.
"""

from __future__ import annotations

from pathlib import Path

#: key -> (label, default on?)
FEATURES: dict[str, tuple[str, bool]] = {
    "reply": ("reply with text", True),
    "quote": ("quote replies", True),
    "quick_reply": ("reply from the notification, without opening the app", True),
    "files": ("send files", True),
    "images": ("send images", True),
    "read": ("read the screen", True),
    "control": ("operate apps: launch, tap, type, scroll, long-press, swipe, notification buttons", True),
    "screenshot": ("screenshots of allow-listed apps (Android 11+)", False),
    "wake_screen": ("wake the screen before touching the UI", True),
    "battery_alerts": ("alert when the phone is unplugged or the battery is low (server only)", True),
}
DEFAULT = frozenset(k for k, (_, on) in FEATURES.items() if on)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

STEP_FEATURE = {
    "read": "read", "wait_for": "read", "screenshot": "screenshot",
    "launch": "control", "tap": "control", "input": "control", "scroll": "control", "back": "control",
    "home": "control", "long_press": "control", "swipe": "control", "notify_action": "control",
}


class FeatureDisabled(Exception):
    """Raised when code asks for something the configuration turned off."""

    def __init__(self, key: str):
        super().__init__(f"feature '{key}' is off (SPAREDROID_FEATURES)")
        self.key = key


def parse(raw: str) -> frozenset[str]:
    """``default``, ``all``, or a comma list; ``default,screenshot,-quote`` adds / removes."""
    raw = (raw or "default").replace(" ", "")
    out: set[str] = set()
    for item in filter(None, raw.split(",")):
        if item == "default":
            out |= DEFAULT
        elif item == "all":
            out |= set(FEATURES)
        elif item.startswith("-"):
            out.discard(item[1:])
        elif item in FEATURES:
            out.add(item)
        else:
            raise ValueError(f"unknown feature in SPAREDROID_FEATURES: {item} (known: {', '.join(FEATURES)})")
    return frozenset(out)


def for_file(filename: str) -> str:
    return "images" if Path(filename).suffix.lower() in IMAGE_SUFFIXES else "files"
