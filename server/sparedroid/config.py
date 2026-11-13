"""Configuration from environment variables (and an optional ``.env`` file).

Everything is ``SPAREDROID_*``. See ``.env.example`` at the repo root.
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


def _features(raw: str) -> frozenset[str]:
    from .features import parse

    return parse(raw)


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

    apps: tuple[str, ...] = ("com.tencent.wework",)
    """Android package names the phone may watch and operate. Nothing else is ever touched."""

    send_label: str = "发送"
    quote_label: str = "引用"
    """Button texts in the chat app (change for other apps / languages, e.g. "Send", "Reply")."""

    ignore_chats: frozenset[str] = frozenset()
    """Chats the bot must never act in, even with ``*``."""

    host: str = "127.0.0.1"
    port: int = 8788
    public_url: str = ""
    """How the phone reaches this server, e.g. ``https://bot.example.com/sparedroid``."""

    data_dir: Path = field(default_factory=lambda: Path("data"))
    alert_webhook: str = ""
    """Optional WeCom *internal* group robot webhook for alerts (phone offline, send failed...)."""

    features: frozenset[str] = field(default_factory=lambda: _features("default"))
    """What the bot may do. See sparedroid.features; set with SPAREDROID_FEATURES."""

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
            token=e("SPAREDROID_TOKEN", ""),
            bot_name=e("SPAREDROID_BOT_NAME", ""),
            handler=e("SPAREDROID_HANDLER", "examples.echo:handle"),
            chats=_names(e("SPAREDROID_CHATS", "")),
            apps=tuple(a.strip() for a in e("SPAREDROID_APPS", "com.tencent.wework").replace("|", ",").split(",")
                       if a.strip()),
            send_label=e("SPAREDROID_SEND_LABEL", "发送"),
            quote_label=e("SPAREDROID_QUOTE_LABEL", "引用"),
            ignore_chats=_names(e("SPAREDROID_IGNORE_CHATS", "")),
            host=e("SPAREDROID_HOST", "127.0.0.1"),
            port=_int("SPAREDROID_PORT", 8788),
            public_url=e("SPAREDROID_PUBLIC_URL", "").rstrip("/"),
            data_dir=Path(e("SPAREDROID_DATA_DIR", "data")),
            alert_webhook=e("SPAREDROID_ALERT_WEBHOOK", ""),
            features=_features(e("SPAREDROID_FEATURES", "default")),
            mention_sender=e("SPAREDROID_MENTION_SENDER", "true").lower() not in ("0", "false", "no"),
            per_chat_per_minute=_int("SPAREDROID_PER_CHAT_PER_MINUTE", 6),
            global_per_minute=_int("SPAREDROID_GLOBAL_PER_MINUTE", 20),
        )

    def works_in(self, chat: str) -> bool:
        if chat in self.ignore_chats:
            return False
        return "*" in self.chats or chat in self.chats

    def problems(self) -> list[str]:
        out = []
        if len(self.token) < 24:
            out.append("SPAREDROID_TOKEN must be at least 24 characters")
        if not self.apps:
            out.append("SPAREDROID_APPS is empty: the phone would not be allowed to touch any app")
        return out

    def warnings(self) -> list[str]:
        """Fine for notification-forwarding or screen-reading setups; wrong for a chat bot."""
        out = []
        if not self.bot_name:
            out.append("SPAREDROID_BOT_NAME is not set: @-mentions cannot be recognised reliably (chat bot use)")
        if not self.chats:
            out.append("SPAREDROID_CHATS is empty: the bot will not reply in any chat "
                       "(list chat names separated by |, or * for all)")
        return out
