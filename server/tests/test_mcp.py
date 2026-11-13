"""The MCP server, against a fake phone.

`FakePhone` plays both the running `sparedroid serve` process and the handset: it takes queued
commands from the shared database and reports results back through a Bot, like the real pair does.
"""

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from sparedroid.bot import Bot
from sparedroid.config import Config
from sparedroid.mcp import Phone
from sparedroid.store import Store

SHOP = "com.example.shop"
CHAT = "客户群"
SCREEN = ["小店管家", "今日订单", "13", "今日营业额", "¥3,668"]


def make_cfg(tmp_path):
    return Config(token="t" * 32, bot_name="bot", chats=frozenset({CHAT}), data_dir=tmp_path,
                  apps=("com.tencent.wework", SHOP))


class FakePhone(threading.Thread):
    def __init__(self, cfg, db, *, fail=None):
        super().__init__(daemon=True)
        self.bot = Bot(cfg, Store(db), handler=lambda m, b: None)
        self.fail = fail or {}
        self.seen = []
        self.stop = False

    def run(self):
        while not self.stop:
            for cmd in self.bot.commands():
                self.seen.append(cmd)
                payload = {"command_id": cmd["id"], "type": cmd["type"], "ok": True, "package": SHOP}
                if cmd["type"] in self.fail:
                    payload.update(ok=False, error=self.fail[cmd["type"]], message="simulated")
                elif cmd["type"] == "run":
                    payload["screen"] = {"nodes": [{"text": t} for t in SCREEN] + [{"f": "c"}]}
                elif cmd["type"] == "reply_quote":
                    payload["quoted"] = True
                self.bot.handle_events([{"event_id": uuid.uuid4().hex, "type": "command_result", "payload": payload}])
            time.sleep(0.05)


@pytest.fixture
def rig(tmp_path):
    cfg = make_cfg(tmp_path)
    db = tmp_path / "sparedroid.db"
    fake = FakePhone(cfg, db)
    fake.start()
    phone = Phone(cfg, Store(db), timeout_s=5, poll_s=0.05)
    yield phone, fake
    fake.stop = True


def test_read_screen_returns_what_the_phone_saw(rig):
    phone, fake = rig
    out = phone.read_screen(SHOP)
    assert out == {"ok": True, "app": SHOP, "texts": SCREEN}
    assert fake.seen[0]["args"]["steps"][0] == {"do": "launch", "package": SHOP}


def test_actions_read_the_screen_afterwards(rig):
    phone, fake = rig
    out = phone.act({"do": "tap", "text": "数据"})
    assert out["ok"] and out["texts"] == SCREEN
    steps = fake.seen[0]["args"]["steps"]
    assert steps[0] == {"do": "tap", "text": "数据"} and steps[-1] == {"do": "read"}


def test_apps_outside_the_allow_list_are_refused_before_reaching_the_phone(rig):
    phone, fake = rig
    out = phone.read_screen("com.some.bank")
    assert not out["ok"] and "not_allowed_app" in out["error"]
    assert fake.seen == []


def test_phone_failure_is_reported_not_raised(rig):
    phone, fake = rig
    fake.fail = {"run": "not_found"}
    out = phone.act({"do": "tap", "text": "不存在"})
    assert not out["ok"] and "not_found" in out["error"]


def test_timeout_when_the_phone_is_offline(tmp_path):
    cfg = make_cfg(tmp_path)
    phone = Phone(cfg, Store(tmp_path / "sparedroid.db"), timeout_s=0.3, poll_s=0.05)
    out = phone.read_screen()
    assert not out["ok"] and "timeout" in out["error"]


def test_chat_tools_respect_the_chat_allow_list_and_readonly(rig):
    phone, fake = rig
    assert phone.send("陌生群", "hi")["error"] == "chat_not_allowed"
    assert phone.send(CHAT, "hi") == {"ok": True}
    phone.readonly = True
    assert phone.send(CHAT, "hi")["error"] == "readonly"
    assert phone.act({"do": "back"})["error"] == "readonly"
    assert phone.read_screen()["ok"]  # looking is still fine
    assert [c["type"] for c in fake.seen] == ["send_text", "run"]


def test_reply_to_a_mention_quotes_it(rig):
    phone, fake = rig
    mid = phone.store.add_message(chat=CHAT, sender="Alice", text="@bot 在吗", quote_key="@bot 在吗")
    assert phone.mentions()[0]["id"] == mid
    assert phone.reply(mid, "在的", quote=True) == {"ok": True, "quoted": True}
    assert fake.seen[0]["type"] == "reply_quote" and fake.seen[0]["args"]["text"] == "@Alice 在的"
    assert phone.reply("nope", "x", quote=True)["error"] == "unknown_message"


def test_status_and_notifications(rig):
    phone, fake = rig
    assert phone.status()["online"] is False
    fake.bot.heartbeat({"accessibility_connected": True, "listener_connected": True, "app_version": "0.2.0"})
    fake.bot.handle_events([{"event_id": "n1", "type": "notification",
                             "payload": {"package": SHOP, "title": "新订单", "text": "张三 2 件", "chat": "新订单"}}])
    st = phone.status()
    assert st["online"] and st["can_read_and_act"] and st["allowed_apps"] == ["com.tencent.wework", SHOP]
    [n] = phone.notifications(app=SHOP)
    assert (n["title"], n["text"], n["mentioned"]) == ("新订单", "张三 2 件", False)
    assert phone.notifications(app="com.other") == []


def test_notifications_are_capped(tmp_path):
    store = Store(tmp_path / "db")
    for i in range(520):
        store.add_notification(app=SHOP, chat="", title=str(i), text="", mentioned=False)
    rows = store.recent_notifications(1000)
    assert len(rows) == 500 and rows[0]["title"] == "519"


# ---- the real thing: an MCP client over stdio ----

def test_end_to_end_over_stdio(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cfg = make_cfg(tmp_path)
    (tmp_path / ".env").write_text(
        f"SPAREDROID_TOKEN={'t' * 32}\nSPAREDROID_APPS=com.tencent.wework,{SHOP}\n"
        f"SPAREDROID_CHATS={CHAT}\nSPAREDROID_DATA_DIR={tmp_path.as_posix()}\n", encoding="utf-8")
    fake = FakePhone(cfg, tmp_path / "sparedroid.db")
    fake.start()
    server_dir = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "sparedroid", "mcp"],
        env={**os.environ, "SPAREDROID_HOME": str(tmp_path), "PYTHONPATH": str(server_dir)})

    async def go():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                screen = await session.call_tool("read_screen", {"app": SHOP})
                blocked = await session.call_tool("read_screen", {"app": "com.some.bank"})
                return names, screen, blocked

    def payload(result):
        # field name differs between SDK major versions
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        return structured or json.loads(result.content[0].text)

    try:
        names, screen, blocked = asyncio.run(asyncio.wait_for(go(), 60))
    finally:
        fake.stop = True
    assert {"phone_status", "read_screen", "tap", "type_text", "recent_mentions",
            "reply_to_message", "send_message", "send_file", "recent_notifications"} <= names
    assert payload(screen) == {"ok": True, "app": SHOP, "texts": SCREEN}
    assert payload(blocked)["ok"] is False
