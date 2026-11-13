"""End-to-end through the Bot (no phone, no network): notification -> read -> handler -> command."""

import hashlib
import json
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from sparedroid import Message, Reply
from sparedroid.bot import Bot
from sparedroid.config import Config
from sparedroid.http import make_handler
from sparedroid.store import Store
from sparedroid.text import norm

NBSP = "\xa0"
CHAT = "客户群A"
TOKEN = "t" * 32
NOTICE = "[有人@我]Alice : @mybot 营业时间是几点"
BUBBLE = f"@mybot{NBSP}营业时间是几点"


@pytest.fixture
def make_bot(tmp_path):
    def make(handler=lambda m, b: f"echo:{m.body}", **cfg):
        alerts = []
        c = Config(token=TOKEN, bot_name="mybot", chats=frozenset({CHAT}), data_dir=tmp_path, **cfg)
        bot = Bot(c, Store(tmp_path / "db.sqlite"), handler, alert=alerts.append)
        return bot, alerts
    return make


def ev(kind, payload):
    return {"event_id": uuid.uuid4().hex, "type": kind, "payload": payload}


def mention(bot, chat=CHAT, text=NOTICE):
    bot.handle_events([ev("notification", {"chat": chat, "mentioned": True, "can_reply": True, "text": text})])


def report(bot, cmd, ok=True, **extra):
    bot.handle_events([ev("command_result", {"command_id": cmd["id"], "type": cmd["type"], "ok": ok, **extra})])


def screen(*bubbles):
    return {"nodes": [{"text": f"{CHAT}(3)"}] + [{"text": b} for b in bubbles]}


def converse(bot, bubbles=(BUBBLE,), notice=NOTICE):
    mention(bot, text=notice)
    [snap] = bot.commands()
    assert snap["type"] == "snapshot"
    report(bot, snap, screen=screen(*bubbles))
    return bot.commands()


def test_reply_flows_back_with_sender_prefix(make_bot):
    bot, alerts = make_bot()
    [cmd] = converse(bot)
    assert cmd["type"] == "send_text" and cmd["args"] == {
        "chat": CHAT, "text": "@Alice echo:营业时间是几点", "expires_at": cmd["args"]["expires_at"],
        "send_label": "发送", "quote_label": "引用"}
    assert alerts == []


def test_handler_gets_a_clean_message(make_bot):
    seen = []
    bot, _ = make_bot(handler=lambda m, b: seen.append(m))
    converse(bot)
    [m] = seen
    assert (m.chat, m.sender, m.body, m.mention_first) == (CHAT, "Alice", "营业时间是几点", True)


def test_unlisted_chat_and_ignore_list(make_bot):
    bot, _ = make_bot()
    mention(bot, chat="陌生群")
    assert bot.commands() == []
    bot.cfg.chats = frozenset({"*"})
    bot.cfg.ignore_chats = frozenset({"内部群"})
    mention(bot, chat="陌生群")
    assert len(bot.commands()) == 1
    mention(bot, chat="内部群")
    assert bot.commands() == []


def test_none_means_no_reply(make_bot):
    bot, _ = make_bot(handler=lambda m, b: None)
    assert converse(bot) == []


def test_quote_reply_and_no_mention(make_bot):
    bot, _ = make_bot(handler=lambda m, b: Reply("ok", quote=True, mention_sender=False))
    [cmd] = converse(bot)
    assert cmd["type"] == "reply_quote"
    assert cmd["args"]["quote_key"] == norm(BUBBLE) and cmd["args"]["text"] == "ok"


def test_only_the_triggering_message_is_answered(make_bot):
    seen = []
    bot, _ = make_bot(handler=lambda m, b: seen.append(m.body))
    converse(bot, bubbles=(f"@mybot{NBSP}旧问题", "Alice(Alice)", f"@mybot{NBSP}你好"),
             notice="[2条]Alice : @mybot 你好")
    assert seen == ["你好"]


def test_message_off_screen_is_not_answered(make_bot):
    bot, _ = make_bot()
    assert converse(bot, bubbles=("别的消息",)) == []


def test_duplicate_events_processed_once(make_bot):
    bot, _ = make_bot()
    e = ev("notification", {"chat": CHAT, "mentioned": True, "can_reply": True, "text": NOTICE})
    bot.handle_events([e, e])
    bot.handle_events([e])
    assert len(bot.commands()) == 1


def test_handler_crash_alerts_and_does_not_reply(make_bot):
    bot, alerts = make_bot(handler=lambda m, b: 1 / 0)
    assert converse(bot) == []
    assert len(alerts) == 1 and "ZeroDivisionError" in alerts[0]


def test_later_reply_by_message_id(make_bot):
    bot, _ = make_bot(handler=lambda m, b: None)
    converse(bot)
    [m] = bot.store.recent_messages()
    bot.reply(m["id"][:6], "done!", quote=True)
    [cmd] = bot.commands()
    assert cmd["type"] == "reply_quote" and cmd["args"]["text"] == "@Alice done!"
    with pytest.raises(KeyError):
        bot.reply("nope", "x")


def test_rate_limit_per_chat(make_bot):
    bot, alerts = make_bot(handler=lambda m, b: None, per_chat_per_minute=2)
    converse(bot)
    mid = bot.store.recent_messages()[0]["id"]
    ids = [bot.reply(mid, f"r{i}") for i in range(3)]
    assert ids[0] and ids[1] and ids[2] == ""
    assert len(bot.commands()) == 2 and "rate limit" in alerts[-1]


def test_failed_send_alerts(make_bot):
    bot, alerts = make_bot()
    [cmd] = converse(bot)
    report(bot, cmd, ok=False, error="no_route", message="no notification yet")
    assert len(alerts) == 1 and CHAT in alerts[0] and "did not go out" in alerts[0]


def test_lost_and_expired_commands_alert_once(make_bot):
    bot, alerts = make_bot(handler=lambda m, b: None)
    bot.send(CHAT, "hi")
    bot.commands()
    bot.store.conn.execute("UPDATE commands SET sent_at = sent_at - 600")
    bot.send(CHAT, "never fetched")
    bot.store.conn.execute("UPDATE commands SET expires_at = 0 WHERE state = 'pending'")
    bot.tick()
    bot.tick()
    assert len(alerts) == 2 and bot.commands() == []


def test_phone_silence_and_service_health(make_bot):
    bot, alerts = make_bot()
    ok = {"accessibility_connected": True, "listener_connected": True}
    bot.heartbeat(ok)
    bot.store.set_meta("last_heartbeat", "1")
    bot.tick()
    bot.tick()
    assert len(alerts) == 1 and "no heartbeat" in alerts[0]
    bot.heartbeat(ok)
    assert "back online" in alerts[1]
    bot.heartbeat({"accessibility_connected": True, "listener_connected": False})
    bot.heartbeat({"accessibility_connected": True, "listener_connected": False})
    assert len(alerts) == 3 and "notification listener" in alerts[2]


def test_send_file_is_served_only_after_fetch_and_unchanged(make_bot, tmp_path):
    bot, _ = make_bot()
    src = tmp_path / "quote.pdf"
    src.write_bytes(b"%PDF-1.4 hello")
    cid = bot.send_file(CHAT, src, caption="your quote")
    assert bot.file(cid) is None  # not fetched yet
    [cmd] = bot.commands()
    assert cmd["args"]["filename"] == "quote.pdf" and cmd["args"]["path"] == f"files/{cid}"
    src.write_bytes(b"changed later")  # the original can change; we copied it
    assert bot.file(cid) == b"%PDF-1.4 hello"
    (tmp_path / "files" / cid).write_bytes(b"tampered")
    assert bot.file(cid) is None
    assert bot.file("../db") is None


def test_http_requires_token_everywhere(make_bot):
    bot, _ = make_bot()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bot, "/sparedroid"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, token=None, body=None):
        req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"} if token else {},
                                     data=None if body is None else json.dumps(body).encode())
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            return e.code

    try:
        assert call("/sparedroid/commands") == 404
        assert call("/sparedroid/commands", "wrong") == 404
        assert call("/commands", TOKEN) == 404  # wrong prefix
        assert call("/sparedroid/commands", TOKEN) == {"commands": []}
        assert call("/sparedroid/heartbeat", TOKEN, {"accessibility_connected": True}) == {"ok": True}
    finally:
        srv.shutdown()


def test_config_problems():
    assert Config(token="short", bot_name="", chats=frozenset()).problems() and \
        Config(token="x" * 24, bot_name="b", chats=frozenset({"*"})).problems() == []
