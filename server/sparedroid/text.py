"""Text helpers shared by the server and (byte-for-byte) the phone app.

The phone and the server must agree on how to normalise chat text, because
the server later asks the phone to find a bubble on screen by its exact
normalised text (for quote replies). Python's ``str.split()`` and Kotlin's
``\\s`` disagree on what counts as whitespace (e.g. the full-width space
U+3000 typed by Chinese IMEs), so the set is spelled out explicitly here and
in ``BotAccessibilityService.kt``. A test fails if the two drift apart.
"""

from __future__ import annotations

import re

NORM_WS = " \t\n\r\f\v 　    "
_NORM_RE = re.compile("[" + re.escape(NORM_WS) + "]+")

# WeCom notification prefixes such as "[有人@我]" ("someone @-ed you") or
# "[3条]" ("3 messages"), possibly stacked.
_NOTIFY_TAGS = re.compile(r"^(?:\[[^\[\]]{1,8}\])+")
_MENTION = re.compile(r"@\S+")


def norm(s: str) -> str:
    """Collapse every listed whitespace run into one ASCII space and trim."""
    return _NORM_RE.sub(" ", s).strip(" ")


def split_notification(text: str) -> tuple[str, str]:
    """``'[有人@我]Alice : @bot hi'`` -> ``('Alice', '@bot hi')``."""
    text = _NOTIFY_TAGS.sub("", text.strip()).strip()
    sender, sep, content = text.partition(" : ")
    if not sep:
        sender, sep, content = text.partition(": ")
    return (sender.strip(), content.strip()) if sep else ("", text)


def find_trigger_message(texts: list[str], content: str) -> str | None:
    """Pick, from all text on the chat screen, the bubble that triggered the mention.

    Searches bottom-up for the first bubble whose start matches the
    notification content (which may be truncated with an ellipsis). Returns
    None rather than guessing - answering some *other* message on screen is
    worse than not answering.
    """
    key = norm(content).rstrip("…").removesuffix("...").strip()[:30]
    if not key:
        return None
    for s in reversed(texts):
        if norm(s).startswith(key):
            return s
    return None


def strip_leading_mentions(text: str, bot_name: str) -> tuple[bool, str]:
    """Drop the run of ``@someone`` at the start of a message.

    Returns ``(bot_was_in_that_run, remaining_text)``. The bot's own name is
    matched in full first because it may contain spaces; other mentions run
    to the next whitespace. ``@bot2`` is not ``@bot``.
    """
    t = text.replace("\xa0", " ").lstrip()
    found = False
    while t.startswith("@"):
        after = t[len(bot_name) + 1 : len(bot_name) + 2]
        if bot_name and t.startswith("@" + bot_name) and (after == "" or after.isspace()):
            t = t[len(bot_name) + 1 :]
            found = True
        else:
            m = _MENTION.match(t)
            t = t[m.end() :]
        t = t.lstrip()
    return found, t
