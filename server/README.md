# sparedroid (server)

Server side of [SpareDroid](https://github.com/Tonieeie/sparedroid): turn a spare Android phone into an
API for apps that have none. It listens to notifications, reads screens and acts; your Python decides.
First use case: WeCom (企业微信) bots in external groups.

```bash
pip install sparedroid            # core, standard library only
pip install "sparedroid[ai]"      # + the Claude customer-service example
sparedroid serve
```

Your bot's logic is one function:

```python
from sparedroid import Message, Reply

def handle(msg: Message, bot) -> str | Reply | None:
    return f"收到：{msg.body}"
```

See the [main README](https://github.com/Tonieeie/sparedroid#readme) for the phone app and setup.
