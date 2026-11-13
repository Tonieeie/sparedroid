"""Order intake: turn a formatted group message into a row in a spreadsheet, then reply later.

    SPAREDROID_HANDLER=examples.order_intake:handle
    SPAREDROID_ORDERS_CSV=data/orders.csv      (optional, this is the default)

A customer sends, in the group::

    @bot
    #下单
    姓名：张三
    电话：13800000000
    产品：标准版
    数量：2

The bot checks the fields, appends a row to a CSV (swap ``_save`` for your Feishu
table / Google Sheet / database / webhook) and replies "got it". When the order
is done - minutes or days later - quote the original message with the result:

    sparedroid reply <message-id> "张三的订单已完成：https://example.com/invoice/123" --quote

The message id is in the CSV. Or call ``bot.reply(message_id, text, quote=True)``
from your own code. This is the pattern the project was born from.
"""

import csv
import os
import time
from pathlib import Path

from sparedroid import Message, Reply

HEADER = "#下单"
REQUIRED = ["姓名", "电话", "产品", "数量"]
TEMPLATE = HEADER + "\n" + "\n".join(f"{f}：" for f in REQUIRED)


def parse(body: str) -> tuple[dict, list[str]]:
    """Return (fields, problems). Accepts both ':' and '：'."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.replace("：", ":").partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    problems = [f"缺少「{f}」" for f in REQUIRED if not fields.get(f)]
    if fields.get("数量") and not fields["数量"].isdigit():
        problems.append("「数量」要填数字")
    return fields, problems


def _save(msg: Message, fields: dict) -> None:
    path = Path(os.environ.get("SPAREDROID_ORDERS_CSV", "data/orders.csv"))
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel opens it correctly
        w = csv.writer(f)
        if new:
            w.writerow(["时间", "消息ID", "群", "下单人", *REQUIRED])
        w.writerow([time.strftime("%Y-%m-%d %H:%M"), msg.id, msg.chat, msg.sender,
                    *(fields[k] for k in REQUIRED)])


def handle(msg: Message, bot) -> str | Reply | None:
    if not msg.mention_first:
        return "下单请把 @我 放在消息最前面哦～ 😊"
    first = msg.body.strip().splitlines()[0].strip() if msg.body.strip() else ""
    if first in ("模板", "下单模板", "怎么下单"):
        return "下单模板来啦 📋 复制后在最前面 @我、填好发回就行：\n\n" + TEMPLATE
    if first != HEADER:
        return "发「@我 下单模板」就能看到下单格式啦 📋"
    fields, problems = parse(msg.body)
    if problems:
        return "这张单我没能识别出来呢 🥺\n" + "\n".join(f"· {p}" for p in problems) + "\n改好后再发我一次就好～"
    _save(msg, fields)
    return Reply(f"收到 {fields['姓名']} 的订单啦 🎉 正在处理，好了第一时间回复你～", quote=True)
