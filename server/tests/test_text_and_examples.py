import re
from pathlib import Path

import pytest

from examples import echo, keyword_faq, order_intake
from wecomdroid import Message, Reply
from wecomdroid.text import NORM_WS, find_trigger_message, norm, split_notification, strip_leading_mentions

ROOT = Path(__file__).resolve().parents[2]
NBSP = "\xa0"


def msg(body, mention_first=True, text=None):
    return Message(id="m1", chat="群", sender="Alice", text=text or f"@bot {body}", body=body,
                   mention_first=mention_first)


# ---- text ----

def test_norm():
    assert norm(f"@bot{NBSP}\n#下单　a\r\nb  ") == "@bot #下单 a b"


def test_norm_whitespace_matches_the_phone_app():
    """The phone finds a bubble by norm(text); both sides must use the same whitespace set."""
    kt = next(ROOT.glob("android/app/src/main/java/**/BotAccessibilityService.kt")).read_text(encoding="utf-8")
    lit = re.search(r'const val NORM_WS = "(.*?)"', kt).group(1)
    esc = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\", '"': '"'}
    out, i = [], 0
    while i < len(lit):
        if lit[i] == "\\" and lit[i + 1] == "u":
            out.append(chr(int(lit[i + 2:i + 6], 16)))
            i += 6
        elif lit[i] == "\\":
            out.append(esc[lit[i + 1]])
            i += 2
        else:
            out.append(lit[i])
            i += 1
    assert "".join(out) == NORM_WS


@pytest.mark.parametrize(("raw", "want"), [
    ("[有人@我]Alice : @bot hi", ("Alice", "@bot hi")),
    ("[3条][有人@我]Bob Li : @bot 你好", ("Bob Li", "@bot 你好")),
    ("Carol: hi", ("Carol", "hi")),
    ("no sender", ("", "no sender")),
])
def test_split_notification(raw, want):
    assert split_notification(raw) == want


def test_find_trigger_message_uses_truncated_prefix_and_bottom_most():
    texts = ["@bot #下单 姓名：旧", "@bot #下单 姓名：张三 电话：1", "@bot #下单 姓名：张三 电话：1"]
    assert find_trigger_message(texts, "@bot #下单 姓名：张三…") is texts[2]
    assert find_trigger_message(texts, "@bot 不存在") is None
    assert find_trigger_message(texts, "") is None


@pytest.mark.parametrize(("text", "found", "rest"), [
    (f"@bot{NBSP}hi", True, "hi"),
    ("@Bob @bot\nhi", True, "hi"),
    ("hi @bot", False, "hi @bot"),
    ("@bot2 hi", False, "hi"),
])
def test_strip_leading_mentions(text, found, rest):
    assert strip_leading_mentions(text, "bot") == (found, rest)


def test_bot_name_with_spaces():
    assert strip_leading_mentions(f"@My Bot{NBSP}hi", "My Bot") == (True, "hi")


# ---- examples ----

def test_echo():
    assert echo.handle(msg("hi"), None) == "收到：hi"


def test_keyword_faq():
    assert "9:00" in keyword_faq.handle(msg("你们营业时间？"), None)
    assert keyword_faq.handle(msg("量子力学"), None) == keyword_faq.FALLBACK


def test_order_intake_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("WECOMDROID_ORDERS_CSV", str(tmp_path / "o.csv"))
    out = order_intake.handle(msg("#下单\n姓名：张三\n电话：138\n产品：标准版\n数量：2"), None)
    assert isinstance(out, Reply) and out.quote and "张三" in out.text
    rows = (tmp_path / "o.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 2 and rows[1].split(",")[1] == "m1"


def test_order_intake_errors_and_template():
    assert "最前面" in order_intake.handle(msg("#下单", mention_first=False), None)
    assert order_intake.TEMPLATE in order_intake.handle(msg("下单模板"), None)
    bad = order_intake.handle(msg("#下单\n姓名：张三\n数量：两个"), None)
    assert "缺少「电话」" in bad and "数字" in bad


def test_order_intake_template_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("WECOMDROID_ORDERS_CSV", str(tmp_path / "o.csv"))
    filled = order_intake.TEMPLATE.replace("姓名：", "姓名：李四").replace("电话：", "电话：1") \
        .replace("产品：", "产品：A").replace("数量：", "数量：1")
    assert isinstance(order_intake.handle(msg(filled), None), Reply)
