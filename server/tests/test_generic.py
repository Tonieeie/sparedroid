"""Beyond chat: notifications from any allow-listed app, generic UI steps, hooks."""

import uuid

import pytest

from examples import notify_forward, screen_watch
from wecomdroid import Notification, Screen
from wecomdroid.bot import Bot, load_handler, load_hooks
from wecomdroid.config import Config
from wecomdroid.store import Store

SHOP = "com.example.shop"


def ev(kind, payload):
    return {"event_id": uuid.uuid4().hex, "type": kind, "payload": payload}


@pytest.fixture
def make(tmp_path):
    def _make(**hooks):
        alerts = []
        cfg = Config(token="t" * 32, bot_name="bot", chats=frozenset({"群"}), data_dir=tmp_path,
                     apps=("com.tencent.wework", SHOP))
        return Bot(cfg, Store(tmp_path / "db"), lambda m, b: "hi", alert=alerts.append, hooks=hooks), alerts
    return _make


def test_on_notification_sees_every_allowed_app_notification(make):
    seen = []
    bot, _ = make(on_notification=lambda n, b: seen.append(n))
    bot.handle_events([ev("notification", {"package": SHOP, "title": "新订单", "text": "张三 下单 2 件",
                                           "chat": "新订单", "mentioned": False, "post_time": 1_700_000_000_000})])
    [n] = seen
    assert isinstance(n, Notification)
    assert (n.app, n.title, n.text, n.mentioned, n.posted_at) == (SHOP, "新订单", "张三 下单 2 件", False, 1.7e9)
    assert bot.commands() == []  # not a mention: nothing is opened or sent


def test_mention_flow_still_works_and_carries_the_app(make):
    got = []
    bot, _ = make()
    bot.handler = lambda m, b: got.append(m.app)
    bot.handle_events([ev("notification", {"package": "com.tencent.wework", "chat": "群", "mentioned": True,
                                           "can_reply": True, "text": "A : @bot hi"})])
    [snap] = bot.commands()
    bot.handle_events([ev("command_result", {"command_id": snap["id"], "type": "snapshot", "ok": True,
                                             "screen": {"nodes": [{"text": "@bot hi"}]}})])
    assert got == ["com.tencent.wework"]


def test_run_steps_and_on_screen(make):
    screens = []
    bot, _ = make(on_screen=lambda s, b: screens.append(s))
    steps = [{"do": "launch", "package": SHOP}, {"do": "tap", "text": "今日"}, {"do": "read"}]
    cid = bot.run(steps, tag="sales")
    [cmd] = bot.commands()
    assert cmd["id"] == cid and cmd["type"] == "run" and cmd["args"]["steps"] == steps
    bot.handle_events([ev("command_result", {"command_id": cid, "type": "run", "ok": True, "package": SHOP,
                                             "screen": {"nodes": [{"text": "今日订单 12"}, {"f": "c"}, {"text": "¥3,400"}]}})])
    [s] = screens
    assert isinstance(s, Screen) and (s.tag, s.ok, s.app, s.texts) == ("sales", True, SHOP, ["今日订单 12", "¥3,400"])


def test_run_refuses_apps_outside_the_allow_list(make):
    bot, _ = make()
    with pytest.raises(ValueError):
        bot.run([{"do": "launch", "package": "com.some.bank"}])
    assert bot.commands() == []


def test_failed_and_lost_runs_reach_on_screen_not_the_alert_channel(make):
    screens = []
    bot, alerts = make(on_screen=lambda s, b: screens.append(s))
    cid = bot.run([{"do": "read"}], tag="x")
    bot.commands()
    bot.handle_events([ev("command_result", {"command_id": cid, "type": "run", "ok": False,
                                             "error": "not_found", "message": "屏幕上没找到「今日」"})])
    bot.run([{"do": "read"}], tag="y")
    bot.store.conn.execute("UPDATE commands SET expires_at = 0 WHERE state = 'pending'")
    bot.tick()
    assert [(s.tag, s.ok) for s in screens] == [("x", False), ("y", False)]
    assert "not_found" in screens[0].error and alerts == []


def test_hook_crash_alerts_but_does_not_break_the_bot(make):
    bot, alerts = make(on_notification=lambda n, b: 1 / 0, on_tick=lambda b: 1 / 0)
    bot.handle_events([ev("notification", {"package": SHOP, "title": "x", "text": "y", "mentioned": False})])
    bot.tick()
    assert len(alerts) == 2 and "on_notification" in alerts[0] and "on_tick" in alerts[1]


def test_labels_are_sent_with_chat_commands(make):
    bot, _ = make()
    bot.cfg.send_label, bot.cfg.quote_label = "Send", "Reply"
    bot.send("群", "hi")
    assert bot.commands()[0]["args"]["send_label"] == "Send"


def test_hooks_are_loaded_from_the_handler_module():
    assert set(load_hooks("examples.screen_watch")) == {"on_screen", "on_tick"}
    assert set(load_hooks("examples.notify_forward")) == {"on_notification"}
    assert load_hooks("examples.echo:handle") == {}
    assert load_handler("examples.notify_forward")(None, None) is None  # no handle(): stays quiet in chats


# ---- examples ----

def note(title, text, app=SHOP):
    return Notification(app=app, title=title, text=text, chat=title, mentioned=False, posted_at=0, raw={})


def test_notify_forward_filters_and_posts(monkeypatch):
    sent = []
    monkeypatch.setenv("FORWARD_WEBHOOK", "https://hooks.example.com/x")
    monkeypatch.setenv("FORWARD_KEYWORDS", "新订单|告警")
    monkeypatch.setattr(notify_forward.urllib.request, "urlopen",
                        lambda req, timeout: sent.append(req.data.decode()) or type("R", (), {"read": lambda s: b""})())
    notify_forward.on_notification(note("新订单", "张三 2 件"), None)
    notify_forward.on_notification(note("促销", "全场五折"), None)
    assert len(sent) == 1 and "张三 2 件" in sent[0] and SHOP in sent[0]


def test_screen_watch_alerts_on_change(monkeypatch):
    monkeypatch.setenv("WATCH_APP", SHOP)
    monkeypatch.setenv("WATCH_PATTERN", r"今日订单\s*(\d+)")
    monkeypatch.setenv("WATCH_TAP", "数据")
    monkeypatch.setattr(screen_watch, "_state", {"next": 0.0, "last": None})

    class B:
        ran, alerts = [], []
        def run(self, steps, tag=""): self.ran.append((steps, tag))
        def alert(self, t): self.alerts.append(t)

    b = B()
    screen_watch.on_tick(b)
    screen_watch.on_tick(b)  # not due again yet
    [(steps, tag)] = b.ran
    assert tag == "watch" and steps[0] == {"do": "launch", "package": SHOP} and steps[-2:] == [{"do": "read"}, {"do": "home"}]
    assert {"do": "tap", "text": "数据", "contains": True} in steps

    def screen(*texts):
        return Screen(tag="watch", ok=True, app=SHOP, texts=list(texts))

    screen_watch.on_screen(screen("今日订单 12"), b)
    screen_watch.on_screen(screen("今日订单 12"), b)
    assert b.alerts == []
    screen_watch.on_screen(screen("今日订单 15"), b)
    assert len(b.alerts) == 1 and "12 → 15" in b.alerts[0]
