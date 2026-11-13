"""Hello world: reply with what was said. Use it to check the whole loop works.

    SPAREDROID_HANDLER=examples.echo:handle
"""

from sparedroid import Message


def handle(msg: Message, bot) -> str:
    return f"收到：{msg.body or '（空消息）'}"
