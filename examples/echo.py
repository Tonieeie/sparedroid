"""Hello world: reply with what was said. Use it to check the whole loop works.

    WECOMDROID_HANDLER=examples.echo:handle
"""

from wecomdroid import Message


def handle(msg: Message, bot) -> str:
    return f"收到：{msg.body or '（空消息）'}"
