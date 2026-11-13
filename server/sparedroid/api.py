"""The public API a handler sees.

A handler is any function ``handle(msg: Message, bot: Actions) -> str | Reply | None``:

* return a ``str``      -> the bot replies with that text in the same chat
* return ``Reply(...)`` -> more control (quote the original, no @sender)
* return ``None``       -> no reply
* call ``bot.*``        -> do more, or do it later (e.g. after a slow job finishes)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Message:
    id: str
    """Stable id. Keep it if you want to quote-reply to this message later."""

    chat: str
    """Group (or contact) name, exactly as WeCom shows it."""

    sender: str
    text: str
    """The whole message as it appears in the chat bubble."""

    body: str
    """``text`` with the leading ``@mentions`` removed. Usually what you want."""

    mention_first: bool
    """True when the message *starts* with @bot (vs. mentioning it mid-sentence)."""

    app: str = "com.tencent.wework"
    """Android package the message came from."""


@dataclass(frozen=True)
class Notification:
    """Any notification from an allow-listed app, as the phone saw it. See ``on_notification``."""

    app: str
    """Android package name, e.g. ``com.tencent.wework``."""

    title: str
    text: str
    chat: str
    """Conversation title when the app provides one, else the notification title."""

    mentioned: bool
    posted_at: float
    """Unix seconds."""

    raw: dict
    """Everything the phone sent (big_text, text_lines, messages, ...)."""


@dataclass(frozen=True)
class Screen:
    """Result of a ``bot.run([...])`` you queued earlier. See ``on_screen``."""

    tag: str
    """Whatever you passed as ``tag=`` to ``bot.run``."""

    ok: bool
    app: str
    """Package in the foreground when the steps finished."""

    texts: list[str]
    """All visible text from the last ``read`` step, top to bottom."""

    error: str = ""
    raw: dict | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    quote: bool = False
    """Quote the original message (long-press -> Quote). Falls back to a plain reply."""

    mention_sender: bool | None = None
    """Override SPAREDROID_MENTION_SENDER for this reply."""


class Actions(Protocol):
    def reply(self, msg: Message | str, text: str, *, quote: bool = False) -> str:
        """Reply to a message (object or id). Returns the command id."""

    def send(self, chat: str, text: str) -> str:
        """Send text to a chat that recently messaged the bot."""

    def send_file(self, chat: str, path: Path | str, *, caption: str = "", filename: str = "") -> str:
        """Share a file into any chat by name (works days later; uses WeCom's share sheet)."""

    def run(self, steps: list[dict], *, tag: str = "") -> str:
        """Drive any allow-listed app: launch / read / tap / input / scroll / back / home / wait.

        The outcome arrives later in your ``on_screen(screen, bot)`` hook.
        """

    def alert(self, text: str) -> None:
        """Tell your team (SPAREDROID_ALERT_WEBHOOK), e.g. "this customer needs a human"."""
