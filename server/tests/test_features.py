"""Feature switches, quick reply, images, screenshots and battery alerts."""

import base64
import uuid

import pytest

from sparedroid.bot import Bot
from sparedroid.config import Config
from sparedroid.features import DEFAULT, FEATURES, FeatureDisabled, for_file, parse
from sparedroid.store import Store

CHAT = "群"


@pytest.fixture
def make(tmp_path):
    def _make(features="default", **hooks):
        alerts = []
        cfg = Config(token="t" * 32, bot_name="bot", chats=frozenset({CHAT}), data_dir=tmp_path,
                     apps=("com.tencent.wework", "com.x"), features=parse(features))
        return Bot(cfg, Store(tmp_path / "db"), lambda m, b: None, alert=alerts.append, hooks=hooks), alerts
    return _make


def ev(kind, payload):
    return {"event_id": uuid.uuid4().hex, "type": kind, "payload": payload}


# ---- parsing ----

def test_parse_defaults_add_remove():
    assert parse("default") == DEFAULT and "screenshot" not in DEFAULT
    assert parse("") == DEFAULT
    assert parse("all") == frozenset(FEATURES)
    assert parse("default,screenshot,-quote") == (DEFAULT | {"screenshot"}) - {"quote"}
    assert parse("reply,read") == {"reply", "read"}
    with pytest.raises(ValueError):
        parse("default,teleport")


def test_file_kind():
    assert for_file("a.PNG") == "images" and for_file("x.jpeg") == "images"
    assert for_file("quote.pdf") == "files" and for_file("noext") == "files"


def test_phone_and_server_know_the_same_features():
    from pathlib import Path
    import re

    kt = next(Path(__file__).resolve().parents[2].glob("android/**/Features.kt")).read_text(encoding="utf-8")
    phone = dict(re.findall(r'Feature\("(\w+)", "[^"]*", "[^"]*", (true|false)\)', kt))
    server = {k: on for k, (_, on) in FEATURES.items() if k != "battery_alerts"}  # server-only
    assert set(phone) == set(server)
    assert {k for k, v in phone.items() if v == "true"} == {k for k, v in server.items() if v}


# ---- switches are enforced ----

def test_switched_off_features_are_refused(make, tmp_path):
    bot, _ = make("read")
    with pytest.raises(FeatureDisabled):
        bot.send(CHAT, "hi")
    with pytest.raises(FeatureDisabled):
        bot.run([{"do": "tap", "text": "x"}])
    with pytest.raises(FeatureDisabled):
        bot.run([{"do": "screenshot"}])
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(FeatureDisabled):
        bot.send_file(CHAT, pdf)
    bot.run([{"do": "read"}, {"do": "wait_for", "text": "ok"}])  # allowed
    assert [c["type"] for c in bot.commands()] == ["run"]


def test_images_and_files_are_separate_switches(make, tmp_path):
    bot, _ = make("default,-files")
    img, pdf = tmp_path / "p.png", tmp_path / "q.pdf"
    img.write_bytes(b"\x89PNG")
    pdf.write_bytes(b"%PDF")
    bot.send_image(CHAT, img, caption="看图")
    with pytest.raises(FeatureDisabled):
        bot.send_file(CHAT, pdf)
    with pytest.raises(ValueError):
        bot.send_image(CHAT, pdf)
    [cmd] = bot.commands()
    assert cmd["type"] == "share_file" and cmd["args"]["filename"] == "p.png" and cmd["args"]["caption"] == "看图"


def test_automatic_reply_with_reply_switched_off_is_quiet(make):
    bot, alerts = make("read")
    bot.handler = lambda m, b: "hi"
    bot.handle_events([ev("notification", {"chat": CHAT, "mentioned": True, "can_reply": True, "text": "A : @bot x"})])
    [snap] = bot.commands()
    bot.handle_events([ev("command_result", {"command_id": snap["id"], "type": "snapshot", "ok": True,
                                             "screen": {"nodes": [{"text": "@bot x"}]}})])
    assert bot.commands() == [] and alerts == []


# ---- quick reply ----

def test_plain_replies_ask_for_quick_reply_first(make):
    bot, _ = make()
    bot.send(CHAT, "hi")
    assert bot.commands()[0]["args"]["prefer_quick"] is True
    bot2, _ = make("default,-quick_reply")
    bot2.send(CHAT, "hi")
    assert "prefer_quick" not in bot2.commands()[0]["args"]


def test_quote_replies_never_use_quick_reply(make):
    bot, _ = make()
    mid = bot.store.add_message(chat=CHAT, sender="A", text="@bot x", quote_key="@bot x")
    bot.reply(mid, "ok", quote=True)
    [cmd] = bot.commands()
    assert cmd["type"] == "reply_quote" and "prefer_quick" not in cmd["args"]


# ---- screenshots ----

def test_screenshot_is_saved_and_kept_out_of_the_database(make, tmp_path):
    shots = []
    bot, _ = make("default,screenshot", on_screen=lambda s, b: shots.append(s))
    cid = bot.run([{"do": "screenshot"}], tag="look")
    bot.commands()
    jpeg = b"\xff\xd8\xff fake jpeg"
    bot.handle_events([ev("command_result", {"command_id": cid, "type": "run", "ok": True, "package": "com.x",
                                             "screenshot": {"format": "jpeg", "width": 2, "height": 2,
                                                            "data": base64.b64encode(jpeg).decode()}})])
    [s] = shots
    assert s.screenshot and open(s.screenshot, "rb").read() == jpeg
    stored = bot.store.command(cid)["result"]
    assert "fake" not in stored and base64.b64encode(jpeg).decode() not in stored


def test_only_the_newest_screenshots_are_kept(make, tmp_path):
    bot, _ = make("default,screenshot")
    for i in range(55):
        bot._save_screenshot(f"{i:08d}xxxx", {"data": base64.b64encode(b"x").decode()})
    assert len(list((tmp_path / "screenshots").glob("*.jpg"))) <= 50


# ---- battery ----

def test_battery_alerts_once_per_change(make):
    bot, alerts = make()
    hb = {"accessibility_connected": True, "listener_connected": True}
    bot.heartbeat({**hb, "plugged": True, "battery_level": 90})
    bot.heartbeat({**hb, "plugged": False, "battery_level": 88})
    bot.heartbeat({**hb, "plugged": False, "battery_level": 80})
    bot.heartbeat({**hb, "plugged": False, "battery_level": 19})
    bot.heartbeat({**hb, "plugged": False, "battery_level": 15})
    bot.heartbeat({**hb, "plugged": True, "battery_level": 16})
    assert len(alerts) == 3
    assert "unplugged" in alerts[0] and "19%" in alerts[1] and "charging again" in alerts[2]


def test_battery_alerts_can_be_switched_off(make):
    bot, alerts = make("default,-battery_alerts")
    bot.heartbeat({"accessibility_connected": True, "listener_connected": True, "plugged": True})
    bot.heartbeat({"accessibility_connected": True, "listener_connected": True, "plugged": False, "battery_level": 5})
    assert alerts == []
