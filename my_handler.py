"""Your bot's brain. Edit this file, restart, done.

Set WECOMDROID_HANDLER=my_handler:handle in .env to use it.
See examples/ for an FAQ bot, an AI customer service bot and an order-intake bot.
"""

from wecomdroid import Message, Reply


def handle(msg: Message, bot) -> str | Reply | None:
    # msg.chat    which group
    # msg.sender  who
    # msg.body    what they said, without the leading @mentions
    if "你好" in msg.body or "hello" in msg.body.lower():
        return "你好呀 👋 有什么可以帮你的？"
    return None  # stay quiet
