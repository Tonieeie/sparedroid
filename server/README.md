# wecomdroid (server)

Server side of [WeComDroid](https://github.com/Tonieeie/wecomdroid): turn a spare Android phone
into a WeCom (企业微信) group bot that works in external groups.

```bash
pip install wecomdroid            # core, standard library only
pip install "wecomdroid[ai]"      # + the Claude customer-service example
wecomdroid serve
```

Your bot's logic is one function:

```python
from wecomdroid import Message, Reply

def handle(msg: Message, bot) -> str | Reply | None:
    return f"收到：{msg.body}"
```

See the [main README](https://github.com/Tonieeie/wecomdroid#readme) for the phone app and setup.
