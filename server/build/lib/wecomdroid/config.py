"""Configuration from environment variables (and an optional ``.env`` file).

Everything is ``WECOMDROID_*``. See ``.env.example`` at the repo root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Minimal .env reader. Existing environment variables win. No inline comments."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _names(raw: str) -> frozenset[str]:
    """Chat names separated by ``|`` (chat names may contain commas)."""
    return frozenset(n.strip() for n in raw.split("|") if n.strip())


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() else default


@dataclass
class Config:
    token: str
    """Shared secret the phone sends as ``Authorization: Bearer ...``. At least 24 chars."""

    bot_name: str
    """The bot account's display name in WeCom groups, exactly as shown."""

    handler: str = "examples.echo:handle"
    """``module:function`` that decides what to reply. See README "Write your own handler"."""

    chats: frozenset[str] = frozenset()
    """Chats the bot works in. ``*`` means every chat it is a member of."""

    ignore_chats: frozenset[str] = frozenset()
    """Chats the bot must never act in, even with ``*``."""

    host: str = "127.0.0.1"
    port: int = 8788
    public_url: str = ""
    """How the phone reaches this server, e.g. ``https://bot.example.com/wecomdroid``."""

    data_dir: Path = field(default_factory=lambda: Path("data"))
    alert_webhook: str = ""
    """Optional WeCom *internal* group robot webhook for alerts (phone offline, send failed...)."""

    mention_sender: bool = True
    """Prefix replies with ``@sender`` (plain text, so readers know who is being answered)."""

    per_chat_per_minute: int = 6
    global_per_minute: int = 20
    """Reply rate limits. Bursty bot behaviour is what gets accounts flagged."""

    @classmethod
    def from_env(cls, env_file: Path | None = Path(".env")) -> "Config":
        if env_file:
            load_dotenv(env_file)
        e = os.environ.get
        return cls(
            token=e("WECOMDROID_TOKEN", ""),
            bot_name=e("WECOMDROID_BOT_NAME", ""),
            handler=e("WECOMDROID_HANDLER", "examples.echo:handle"),
            chats=_names(e("WECOMDROID_CHATS", "")),
            ignore_chats=_names(e("WECOMDROID_IGNORE_CHATS", "")),
            host=e("WECOMDROID_HOST", "127.0.0.1"),
            port=_int("WECOMDROID_PORT", 8788),
            public_url=e("WECOMDROID_PUBLIC_URL", "").rstrip("/"),
            data_dir=Path(e("WECOMDROID_DATA_DIR", "data")),
            alert_webhook=e("WECOMDROID_ALERT_WEBHOOK", ""),
            mention_sender=e("WECOMDROID_MENTION_SENDER", "true").lower() not in ("0", "false", "no"),
            per_chat_per_minute=_int("WECOMDROID_PER_CHAT_PER_MINUTE", 6),
            global_per_minute=_int("WECOMDROID_GLOBAL_PER_MINUTE", 20),
        )

    def works_in(self, chat: str) -> bool:
        if chat in self.ignore_chats:
            return False
        return "*" in self.chats or chat in self.chats

    def problems(self) -> list[str]:
        out = []
        if len(self.token) < 24:
            out.append("WECOMDROID_TOKEN must be at least 24 characters")
        if not self.bot_name:
            out.append("WECOMDROID_BOT_NAME is required (the bot's display name in groups)")
        if not self.chats:
            out.append("WECOMDROID_CHATS is empty, so the bot will ignore every chat "
                       "(list chat names separated by |, or * for all)")
        return out
