"""The bot: phone events in, handler decides, phone commands out.

Flow for one message::

    phone: WeCom notification "[有人@我]Alice : @bot hi"  ──► _on_notification
    server: "please open that chat and read the screen"   ──► snapshot command
    phone: all text on screen                             ──► _on_snapshot
    server: find the bubble that triggered it, call handler(msg, bot)
    server: handler's reply                               ──► send_text / reply_quote command

Everything that can silently go wrong (phone offline, a reply that never
went out) is reported to the alert webhook, because the worst failure for a
customer-facing bot is the one nobody notices.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import shutil
import threading
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path
from typing import Callable

from .api import Message, Notification, Reply, Screen
from .config import Config
from .store import Store
from .text import find_trigger_message, norm, split_notification, strip_leading_mentions

log = logging.getLogger("wecomdroid")

READ_TTL_S = 120          # a reply nobody saw within 2 minutes is stale
REPLY_TTL_S = 24 * 3600   # explicit / later replies
FILE_TTL_S = 72 * 3600
PHONE_SILENT_AFTER_S = 300

Handler = Callable[[Message, "Bot"], "str | Reply | None"]


def load_handler(spec: str) -> Handler:
    module, _, func = spec.partition(":")
    return getattr(importlib.import_module(module), func or "handle", None) or (lambda msg, bot: None)


def load_hooks(spec: str) -> dict:
    """Optional functions in the handler's module:

    * ``on_notification(n: Notification, bot)`` - every notification from an allow-listed app
    * ``on_screen(screen: Screen, bot)``        - result of a ``bot.run([...])``
    * ``on_tick(bot)``                          - called about every 30 seconds
    """
    module = importlib.import_module(spec.partition(":")[0])
    return {name: getattr(module, name) for name in ("on_notification", "on_screen", "on_tick")
            if callable(getattr(module, name, None))}


class Bot:
    def __init__(self, cfg: Config, store: Store, handler: Handler, *,
                 alert: Callable[[str], None] | None = None, hooks: dict | None = None):
        self.cfg = cfg
        self.store = store
        self.handler = handler
        self.hooks = hooks or {}
        self.lock = threading.RLock()
        self._alert = alert or self._webhook_alert
        self._sent: dict[str, deque] = {}

    # ------------------------------------------------------------------ alerts

    def _webhook_alert(self, text: str) -> None:
        if not self.cfg.alert_webhook:
            return
        body = json.dumps({"msgtype": "markdown", "markdown": {"content": text}}).encode()
        req = urllib.request.Request(self.cfg.alert_webhook, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()

    def alert(self, text: str) -> None:
        log.warning("ALERT: %s", text.replace("\n", " | "))
        try:
            self._alert(text)
        except Exception:  # noqa: BLE001 - alerting must never take the bot down
            log.exception("alert webhook failed")

    # --------------------------------------------------------- phone -> server

    def handle_events(self, events: list[dict]) -> None:
        for ev in events:
            with self.lock:
                try:
                    if self.store.first_time(str(ev.get("event_id"))):
                        self._handle(ev)
                except Exception:  # noqa: BLE001 - one bad event must not block the batch
                    log.exception("event %s failed", ev.get("type"))

    def _handle(self, ev: dict) -> None:
        p = ev.get("payload") or {}
        kind = ev.get("type")
        if kind == "notification":
            self._on_notification(p)
        elif kind == "command_result":
            self._on_result(p)
        elif kind == "ui_dump":
            self._save_dump("dump", p)

    def _hook(self, name: str, *args) -> None:
        fn = self.hooks.get(name)
        if fn is None:
            return
        try:
            fn(*args, self)
        except Exception as exc:  # noqa: BLE001 - user code must not take the bot down
            log.exception("%s failed", name)
            self.alert(f"**WeComDroid**: {name} crashed: {type(exc).__name__}: {exc}")

    def _on_notification(self, p: dict) -> None:
        chat = p.get("chat") or ""
        app = p.get("package") or "com.tencent.wework"
        self._hook("on_notification", Notification(
            app=app, title=p.get("title") or "", text=p.get("big_text") or p.get("text") or "",
            chat=chat, mentioned=bool(p.get("mentioned")), posted_at=(p.get("post_time") or 0) / 1000, raw=p))
        if not p.get("mentioned"):
            return
        if not self.cfg.works_in(chat):
            log.info("mentioned in %r, which is not in WECOMDROID_CHATS; ignoring", chat)
            return
        if not p.get("can_reply"):
            log.warning("notification from %r has no way to open the chat", chat)
            return
        sender, content = split_notification(p.get("text") or p.get("ticker") or "")
        log.info("%s mentioned the bot in %r; reading the chat", sender, chat)
        self.store.enqueue("snapshot", {"chat": chat}, ttl_s=READ_TTL_S,
                           context={"purpose": "read", "sender": sender, "content": content, "app": app})

    def _on_result(self, p: dict) -> None:
        ok = bool(p.get("ok"))
        brief = {k: v for k, v in p.items() if k not in ("screen", "screen_on_error", "dump")}
        cmd = self.store.finish(str(p.get("command_id")), ok, brief)
        if cmd is None:
            return
        log.info("result %s/%s: %s", cmd["type"], cmd["context"].get("purpose"),
                 "ok" if ok else f"{p.get('error')}: {p.get('message')}")
        if cmd["type"] == "run":
            nodes = (p.get("screen") or {}).get("nodes") or []
            self._hook("on_screen", Screen(
                tag=cmd["context"].get("tag", ""), ok=ok, app=p.get("package") or "",
                texts=[n["text"] for n in nodes if n.get("text")],
                error="" if ok else f"{p.get('error')}: {p.get('message')}", raw=p))
            return
        if ok and cmd["type"] == "snapshot":
            self._on_snapshot(cmd["args"]["chat"], p.get("screen") or {}, cmd["context"])
        elif not ok:
            if p.get("screen_on_error"):
                self._save_dump("error_screen", p["screen_on_error"])
            self._alert_command(cmd, f"{p.get('error')}: {p.get('message')}")

    def _on_snapshot(self, chat: str, screen: dict, ctx: dict) -> None:
        texts = [n.get("text") for n in screen.get("nodes") or [] if n.get("text")]
        text = find_trigger_message(texts, ctx.get("content", ""))
        if text is None:
            log.warning("could not find %s's message on screen in %r; not replying", ctx.get("sender"), chat)
            return
        mention_first, body = strip_leading_mentions(text, self.cfg.bot_name)
        mid = self.store.add_message(chat=chat, sender=ctx.get("sender", ""), text=text, quote_key=norm(text))
        msg = Message(id=mid, chat=chat, sender=ctx.get("sender", ""), text=text,
                      body=body, mention_first=mention_first, app=ctx.get("app", "com.tencent.wework"))
        try:
            out = self.handler(msg, self)
        except Exception as exc:  # noqa: BLE001
            log.exception("handler failed")
            self.alert(f"**WeComDroid**: handler crashed on a message from {msg.sender} in 「{chat}」: "
                       f"{type(exc).__name__}: {exc}")
            return
        if out is None:
            return
        reply = Reply(out) if isinstance(out, str) else out
        self.reply(msg, reply.text, quote=reply.quote, mention_sender=reply.mention_sender,
                   ttl_s=READ_TTL_S, purpose="reply")

    def heartbeat(self, hb: dict) -> None:
        with self.lock:
            self.store.set_meta("last_heartbeat", str(time.time()))
            self.store.set_meta("last_heartbeat_body", json.dumps(hb, ensure_ascii=False)[:4000])
            if self.store.get_meta("phone") == "silent":
                self.alert("**WeComDroid**: the phone is back online.")
            self.store.set_meta("phone", "ok")
            broken = [label for key, label in (("accessibility_connected", "accessibility service"),
                                               ("listener_connected", "notification listener"))
                      if not hb.get(key)]
            now = ", ".join(broken)
            if now != (self.store.get_meta("phone_health") or ""):
                self.store.set_meta("phone_health", now)
                self.alert(f"**WeComDroid**: on the phone, the {now} stopped. Open the app on the phone to fix it."
                           if now else "**WeComDroid**: the phone's services are healthy again.")

    # --------------------------------------------------------- server -> phone

    def commands(self) -> list[dict]:
        with self.lock:
            return self.store.take_pending()

    def reply(self, msg: Message | str, text: str, *, quote: bool = False,
              mention_sender: bool | None = None, ttl_s: int = REPLY_TTL_S, purpose: str = "reply") -> str:
        """Reply to a message, now or later. ``msg`` may be a Message or its id."""
        with self.lock:
            m = msg if isinstance(msg, Message) else self._message(msg)
            if m is None:
                raise KeyError(f"unknown message: {msg}")
            mention = self.cfg.mention_sender if mention_sender is None else mention_sender
            if mention and m.sender:
                text = f"@{m.sender} {text}"  # plain text, not a real @, but readers see who is answered
            if not self._allow(m.chat):
                self.alert(f"**WeComDroid**: rate limit hit in 「{m.chat}」; dropped a reply to {m.sender}.")
                return ""
            if quote:
                cmd = self.store.enqueue("reply_quote", {"chat": m.chat, "quote_key": norm(m.text), "text": text,
                                                         **self._labels()},
                                         ttl_s=ttl_s, context={"purpose": purpose, "message": m.id})
            else:
                cmd = self.store.enqueue("send_text", {"chat": m.chat, "text": text, **self._labels()},
                                         ttl_s=ttl_s, context={"purpose": purpose, "message": m.id})
            return cmd["id"]

    def _labels(self) -> dict:
        return {"send_label": self.cfg.send_label, "quote_label": self.cfg.quote_label}

    def run(self, steps: list[dict], *, tag: str = "", ttl_s: int = 300) -> str:
        """Queue generic UI steps for any allow-listed app. The outcome arrives in ``on_screen``.

        Steps: ``{"do": "launch", "package": ...}``, ``{"do": "read"}``, ``{"do": "tap", "text": ...}``
        (or ``"x"``/``"y"``), ``{"do": "input", "text": ...}``, ``{"do": "scroll", "direction": "down"}``,
        ``{"do": "back"}``, ``{"do": "home"}``, ``{"do": "wait", "ms": 800}``.
        """
        for s in steps:
            if s.get("do") == "launch" and s.get("package") not in self.cfg.apps:
                raise ValueError(f"{s.get('package')} is not in WECOMDROID_APPS")
        with self.lock:
            return self.store.enqueue("run", {"steps": steps}, ttl_s=ttl_s,
                                      context={"purpose": "run", "tag": tag})["id"]

    def send(self, chat: str, text: str, *, ttl_s: int = REPLY_TTL_S) -> str:
        with self.lock:
            if not self._allow(chat):
                return ""
            return self.store.enqueue("send_text", {"chat": chat, "text": text, **self._labels()}, ttl_s=ttl_s,
                                      context={"purpose": "send"})["id"]

    def send_file(self, chat: str, path: Path | str, *, caption: str = "", filename: str = "",
                  ttl_s: int = FILE_TTL_S) -> str:
        """Copy the file into the data dir now (so later edits/deletes don't matter) and queue it."""
        src = Path(path)
        data = src.read_bytes()
        cid = uuid.uuid4().hex
        files = self.cfg.data_dir / "files"
        files.mkdir(parents=True, exist_ok=True)
        dest = files / cid
        shutil.copyfile(src, dest)
        with self.lock:
            self.store.enqueue("share_file",
                               {"chat": chat, "path": f"files/{cid}", "filename": filename or src.name,
                                "caption": caption, "send_label": self.cfg.send_label},
                               ttl_s=ttl_s, command_id=cid,
                               context={"purpose": "file", "file": str(dest.resolve()),
                                        "sha256": hashlib.sha256(data).hexdigest()})
        return cid

    def file(self, command_id: str) -> bytes | None:
        """Bytes for a share_file command the phone has fetched and that has not expired."""
        if not command_id.isalnum():
            return None
        with self.lock:
            cmd = self.store.command(command_id)
        if cmd is None or cmd["type"] != "share_file" or cmd["state"] != "sent" or cmd["expires_at"] < time.time():
            return None
        path = Path(cmd["context"].get("file", "")).resolve()
        if path.parent != (self.cfg.data_dir / "files").resolve() or not path.is_file():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != cmd["context"].get("sha256"):
            return None
        return data

    # ------------------------------------------------------------ housekeeping

    def tick(self) -> None:
        with self.lock:
            now = time.time()
            last = float(self.store.get_meta("last_heartbeat") or 0)
            if last and now - last > PHONE_SILENT_AFTER_S and self.store.get_meta("phone") != "silent":
                self.store.set_meta("phone", "silent")
                self.alert(f"**WeComDroid**: no heartbeat from the phone for {int((now - last) / 60)} min. "
                           "Mentions in groups will get no answer. Check the phone's network, the app, and WeCom.")
            for cmd in self.store.sweep():
                self._alert_command(cmd, "the phone never fetched it (expired)" if cmd["state"] == "expired"
                                    else "sent to the phone but no result after 3 min; it may or may not have gone out")
            self._hook("on_tick")
            if now - float(self.store.get_meta("pruned_at") or 0) > 86400:
                self.store.prune()
                self.store.set_meta("pruned_at", str(now))

    def _alert_command(self, cmd: dict, why: str) -> None:
        if cmd["type"] == "run":
            self._hook("on_screen", Screen(tag=cmd["context"].get("tag", ""), ok=False, app="", texts=[],
                                           error=why, raw=None))
            return
        if cmd["type"] in ("snapshot", "dump", "home"):
            if cmd["type"] == "snapshot":
                self.alert(f"**WeComDroid**: could not read 「{cmd['args'].get('chat')}」 after "
                           f"{cmd['context'].get('sender', 'someone')} mentioned the bot ({why}).")
            return
        what = {"share_file": "a file", "reply_quote": "a reply", "send_text": "a message"}[cmd["type"]]
        self.alert(f"**WeComDroid**: {what} for 「{cmd['args'].get('chat')}」 did not go out ({why}). "
                   f"Please check the group and send it by hand if needed.\n> {cmd['args'].get('text', cmd['args'].get('filename', ''))[:200]}")

    def _allow(self, chat: str) -> bool:
        now = time.time()
        for key, limit in ((chat, self.cfg.per_chat_per_minute), ("*", self.cfg.global_per_minute)):
            q = self._sent.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                log.warning("rate limit reached for %r", key)
                return False
        for key in (chat, "*"):
            self._sent[key].append(now)
        return True

    def _message(self, mid: str) -> Message | None:
        row = self.store.message(mid)
        if row is None:
            return None
        mention_first, body = strip_leading_mentions(row["text"], self.cfg.bot_name)
        return Message(id=row["id"], chat=row["chat"], sender=row["sender"], text=row["text"],
                       body=body, mention_first=mention_first)

    def _save_dump(self, kind: str, obj: dict) -> None:
        """Screen dumps help adapt to new WeCom versions. Keep only the last 200: they may contain chat text."""
        d = self.cfg.data_dir / "dumps"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{uuid.uuid4().hex[:6]}.json").write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        for old in sorted(d.iterdir())[:-200]:
            old.unlink(missing_ok=True)
