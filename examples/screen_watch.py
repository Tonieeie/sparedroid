"""Screen reader: open an app on a schedule, read what's on screen, tell you when it changes.

For data that only exists inside an app: today's sales in a merchant app, a queue number,
stock of an item, a status page. No API needed - the phone opens the app and reads the text.

    SPAREDROID_HANDLER=examples.screen_watch
    SPAREDROID_APPS=com.example.merchant
    WATCH_APP=com.example.merchant
    WATCH_PATTERN=今日订单\\s*(\\d+)          (regex; group 1 is the value to track)
    WATCH_TAP=数据|今日                       (optional: texts to tap, in order, to reach the screen)
    WATCH_EVERY_MINUTES=10

When the value changes you get an alert (SPAREDROID_ALERT_WEBHOOK). Swap ``bot.alert`` for
anything: write to a sheet, call your API, reply in a group.
"""

import logging
import os
import re
import time

from sparedroid import Screen

log = logging.getLogger("sparedroid.screen_watch")
_state = {"next": 0.0, "last": None}


def steps() -> list[dict]:
    out = [{"do": "launch", "package": os.environ["WATCH_APP"]}, {"do": "wait", "ms": 1500}]
    for label in filter(None, os.environ.get("WATCH_TAP", "").split("|")):
        out += [{"do": "tap", "text": label, "contains": True}, {"do": "wait", "ms": 800}]
    return out + [{"do": "read"}, {"do": "home"}]


def extract(texts: list[str]) -> str | None:
    m = re.search(os.environ.get("WATCH_PATTERN", r"(\d+)"), "\n".join(texts))
    return (m.group(1) if m.groups() else m.group(0)) if m else None


def on_tick(bot) -> None:
    if time.time() < _state["next"] or not os.environ.get("WATCH_APP"):
        return
    _state["next"] = time.time() + 60 * float(os.environ.get("WATCH_EVERY_MINUTES", "10"))
    bot.run(steps(), tag="watch")


def on_screen(screen: Screen, bot) -> None:
    if screen.tag != "watch":
        return
    if not screen.ok:
        bot.alert(f"**SpareDroid**: 读取 {os.environ.get('WATCH_APP')} 失败：{screen.error}")
        return
    value = extract(screen.texts)
    if value is None:
        log.warning("pattern not found on screen: %s", screen.texts[:8])
        return
    if _state["last"] is not None and value != _state["last"]:
        bot.alert(f"**SpareDroid**: {os.environ.get('WATCH_APP')} 的数值变了：{_state['last']} → {value}")
    _state["last"] = value
