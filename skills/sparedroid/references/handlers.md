# Writing a handler

`SPAREDROID_HANDLER=module:function` points at a Python module (e.g. `my_handler.py` next to `.env`,
`SPAREDROID_HANDLER=my_handler:handle`). The module may define any of these; missing ones are skipped.

| Function | Called when | Return |
|---|---|---|
| `handle(msg, bot)` | someone @-mentions the bot in an allowed chat | `str` reply, `Reply(text, quote=True)`, or `None` |
| `on_notification(n, bot)` | any notification from an allow-listed app | ignored |
| `on_screen(screen, bot)` | a `bot.run([...])` you queued finished (or failed / expired) | ignored |
| `on_tick(bot)` | about every 30 s | ignored |

Exceptions are caught, logged and sent to the alert webhook; they don't stop the server.

## Feature switches

Each capability is a switch (`SPAREDROID_FEATURES` on the server, checkboxes on the phone; both must be on):
reply, quote, quick_reply, files, images, read, control, screenshot (off by default), wake_screen,
battery_alerts. Calling a switched-off one raises `sparedroid.features.FeatureDisabled`.
Plain replies try the notification's own reply button first when `quick_reply` is on (no screen needed).

## Inputs

```python
from sparedroid import Message, Notification, Reply, Screen

msg.chat, msg.sender      # group name, who wrote it
msg.body                  # text without the leading @mentions — usually what you want
msg.text                  # the whole bubble
msg.mention_first         # True if the message starts with @bot
msg.id                    # keep it to reply later

n.app, n.title, n.text, n.chat, n.mentioned, n.posted_at, n.raw

screen.tag, screen.ok, screen.app, screen.texts, screen.error
```

## Actions

```python
bot.reply(msg_or_id, "text", quote=True)        # now or days later; quote attaches it to the original
bot.send(chat, "text")                          # chat must have messaged the bot since the app started
bot.send_file(chat, "/path/file.pdf", caption="...")   # works any time (share sheet), copies the file first
bot.send_image(chat, "/path/pic.png", caption="...")   # same, shown as a picture
bot.run(steps, tag="x")                         # generic UI steps in any allow-listed app -> on_screen
bot.alert("text")                               # internal alert webhook
```

`bot.run` steps (stops at the first failure):

```python
{"do": "launch", "package": "com.example.shop"}
{"do": "read"}                                   # all visible text -> screen.texts
{"do": "tap", "text": "确定"}                    # exact text / accessibility label; "contains": True for substring
{"do": "tap", "x": 540, "y": 1200}
{"do": "input", "text": "..."}
{"do": "scroll", "direction": "down"}            # or "up"
{"do": "back"} / {"do": "home"} / {"do": "wait", "ms": 800}
{"do": "long_press", "text": "..."}
{"do": "swipe", "x1": 500, "y1": 1500, "x2": 500, "y2": 500, "ms": 300}
{"do": "wait_for", "text": "已发送", "timeout_ms": 8000}
{"do": "screenshot"}                         # needs the screenshot feature; path in screen.screenshot
{"do": "notify_action", "chat": "群", "action": "标为已读"}
```

End multi-step runs with `{"do": "home"}`: while the phone sits inside a chat, that chat's new messages don't
raise notifications, so the bot would miss them.

## Patterns

**Answer only well-formed requests.** Check `msg.mention_first` and the first line of `msg.body`; reply with a
short format hint otherwise. Keep replies short and friendly — they are read in a group chat.

**Slow work.** Return a quick "收到" with `Reply(..., quote=True)`, store `msg.id`, do the work elsewhere, then
`bot.reply(msg_id, result, quote=True)` (or `sparedroid reply <id> "..." --quote` from a script).

**AI answers.** Start from `examples/claude_qa.py`: knowledge file in a cached system prompt, answer only from it,
reply "HANDOFF" otherwise and `bot.alert` the team. Never let the model decide to take actions (orders, refunds)
— keep those in deterministic code.

**Reading an app.** `on_tick` schedules `bot.run([...launch, tap, read, home])`; `on_screen` parses
`screen.texts` with a regex. See `examples/screen_watch.py`.

**Forwarding notifications.** `examples/notify_forward.py`: filter by keyword, POST to a webhook.

## Ready-made examples

`examples.echo:handle`, `examples.keyword_faq:handle`, `examples.claude_qa:handle` (needs `ANTHROPIC_API_KEY`,
`pip install "sparedroid[ai]"`), `examples.order_intake:handle`, `examples.notify_forward`,
`examples.screen_watch`. Read the docstring at the top of each for its environment variables.

## Testing a handler without a phone

Call it directly with a `Message` and a stub bot:

```python
from sparedroid import Message
from my_handler import handle
print(handle(Message(id="1", chat="测试群", sender="Alice", text="@bot 你好", body="你好", mention_first=True), None))
```

The repo's `server/tests/test_bot.py` shows how to drive the full flow with fake phone events.
