"""Command line.

    wecomdroid serve                         run the server (what Docker / systemd runs)
    wecomdroid config                        print the one-line config to import on the phone
    wecomdroid status                        last heartbeat, queued commands
    wecomdroid messages                      recent messages that mentioned the bot (with ids)
    wecomdroid reply <msg-id> <text> [--quote]   reply to one of them, now
    wecomdroid send <chat> <text>            send text to a chat that recently messaged the bot
    wecomdroid send-file <chat> <file> [--caption TEXT]

The last three only queue a command in the database; the running server hands it to the phone.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from .bot import Bot, load_handler, load_hooks
from .config import Config
from .http import make_handler
from .store import Store


def _store(cfg: Config) -> Store:
    return Store(cfg.data_dir / "wecomdroid.db")


def serve(cfg: Config) -> None:
    problems = cfg.problems()
    if problems:
        sys.exit("Config problems:\n  - " + "\n  - ".join(problems))
    sys.path.insert(0, ".")  # so WECOMDROID_HANDLER=my_handler:handle works from the working dir
    bot = Bot(cfg, _store(cfg), load_handler(cfg.handler), hooks=load_hooks(cfg.handler))
    prefix = urlparse(cfg.public_url).path if cfg.public_url else ""
    server = ThreadingHTTPServer((cfg.host, cfg.port), make_handler(bot, prefix))
    server.daemon_threads = True

    def patrol() -> None:
        while True:
            time.sleep(30)
            try:
                bot.tick()
            except Exception:  # noqa: BLE001
                logging.exception("tick failed")

    threading.Thread(target=patrol, daemon=True).start()
    log = logging.getLogger("wecomdroid")
    log.info("listening on http://%s:%d%s  handler=%s  hooks=%s", cfg.host, cfg.port, prefix or "/", cfg.handler,
             ",".join(bot.hooks) or "-")
    log.info("apps: %s", ", ".join(cfg.apps))
    log.info("chats: %s%s", "every chat" if "*" in cfg.chats else " | ".join(sorted(cfg.chats)),
             f"  (ignoring: {' | '.join(sorted(cfg.ignore_chats))})" if cfg.ignore_chats else "")
    for w in cfg.warnings():
        log.warning(w)
    if not cfg.alert_webhook:
        log.warning("WECOMDROID_ALERT_WEBHOOK is not set: nobody will be told if the phone goes offline")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles choke on emoji otherwise
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="wecomdroid", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "config", "status", "messages"):
        sub.add_parser(name)
    p = sub.add_parser("reply")
    p.add_argument("message_id")
    p.add_argument("text")
    p.add_argument("--quote", action="store_true")
    p = sub.add_parser("send")
    p.add_argument("chat")
    p.add_argument("text")
    p = sub.add_parser("send-file")
    p.add_argument("chat")
    p.add_argument("file")
    p.add_argument("--caption", default="")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    if a.cmd == "serve":
        serve(cfg)
        return 0
    if a.cmd == "config":
        endpoint = cfg.public_url or f"http://<this-machine-ip>:{cfg.port}"
        print("Copy this whole line to the phone, then tap 「从剪贴板导入配置」 (Import from clipboard):\n")
        print(json.dumps({"endpoint": endpoint, "token": cfg.token, "pin": "", "bot": cfg.bot_name,
                          "apps": list(cfg.apps)}, ensure_ascii=False))
        return 0

    store = _store(cfg)
    bot = Bot(cfg, store, handler=lambda m, b: None)
    if a.cmd == "status":
        last = float(store.get_meta("last_heartbeat") or 0)
        print("phone heartbeat:", f"{int(time.time() - last)}s ago" if last else "never")
        print("phone status   :", store.get_meta("last_heartbeat_body") or "-")
        print("commands       :", {s: store.count(s) for s in ("pending", "sent", "failed", "lost", "expired")})
    elif a.cmd == "messages":
        for m in store.recent_messages():
            when = time.strftime("%m-%d %H:%M", time.localtime(m["at"]))
            print(f"{m['id']}  {when}  [{m['chat']}] {m['sender']}: {m['text'][:60]!r}")
    elif a.cmd == "reply":
        print("queued", bot.reply(a.message_id, a.text, quote=a.quote))
    elif a.cmd == "send":
        print("queued", bot.send(a.chat, a.text))
    elif a.cmd == "send-file":
        print("queued", bot.send_file(a.chat, a.file, caption=a.caption))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
