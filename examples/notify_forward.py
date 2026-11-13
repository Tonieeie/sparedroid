"""Notification bridge: forward notifications from any app on the phone to a webhook.

No chat bot involved - the phone just becomes a "notification → HTTP" adapter for apps
that have no API. Typical uses: a shop app's "new order" push, a courier app's delivery
notice, a monitoring app's alarm → your team's Slack / Feishu / WeCom internal group.

    SPAREDROID_HANDLER=examples.notify_forward
    SPAREDROID_APPS=com.example.shop,com.tencent.wework     (apps to watch)
    FORWARD_WEBHOOK=https://hooks.example.com/...           (receives JSON)
    FORWARD_KEYWORDS=新订单|发货|告警                        (optional: only forward matching ones)

Only apps listed in SPAREDROID_APPS are ever seen. Don't list apps whose notifications
you wouldn't paste into that webhook yourself (banking, 2FA codes, private chats).
"""

import json
import logging
import os
import urllib.request

from sparedroid import Notification

log = logging.getLogger("sparedroid.notify_forward")


def wanted(n: Notification) -> bool:
    keywords = [k for k in os.environ.get("FORWARD_KEYWORDS", "").split("|") if k]
    return not keywords or any(k in n.title or k in n.text for k in keywords)


def payload(n: Notification) -> dict:
    # WeCom / Feishu / DingTalk group robots all accept this "text" shape; adapt for Slack etc.
    return {"msgtype": "text", "text": {"content": f"[{n.app}] {n.title}\n{n.text}"}}


def on_notification(n: Notification, bot) -> None:
    if not wanted(n):
        return
    url = os.environ.get("FORWARD_WEBHOOK", "")
    if not url:
        log.info("would forward: [%s] %s | %s", n.app, n.title, n.text[:80])
        return
    req = urllib.request.Request(url, data=json.dumps(payload(n), ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()
