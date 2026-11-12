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


@dataclass(frozen=True)
class Reply:
    text: str
    quote: bool = False
    """Quote the original message (long-press -> Quote). Falls back to a plain reply."""

    mention_sender: bool | None = None
    """Override WECOMDROID_MENTION_SENDER for this reply."""


class Actions(Protocol):
    def reply(self, msg: Message | str, text: str, *, quote: bool = False) -> str:
        """Reply to a message (object or id). Returns the command id."""

    def send(self, chat: str, text: str) -> str:
        """Send text to a chat that recently messaged the bot."""

    def send_file(self, chat: str, path: Path | str, *, caption: str = "", filename: str = "") -> str:
        """Share a file into any chat by name (works days later; uses WeCom's share sheet)."""

    def alert(self, text: str) -> None:
        """Tell your team (WECOMDROID_ALERT_WEBHOOK), e.g. "this customer needs a human"."""
