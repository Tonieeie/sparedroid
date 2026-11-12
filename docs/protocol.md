# Phone ⇄ server protocol

All requests carry `Authorization: Bearer <WECOMDROID_TOKEN>`. Wrong token and unknown path both
return 404. Paths are relative to the endpoint configured on the phone (e.g. `https://bot.example.com`).

| Direction | Endpoint | Body |
|---|---|---|
| phone → | `POST /events` | `{"events": [{event_id, type, device_id, created_at, payload}]}` |
| phone → | `POST /heartbeat` | every 60 s: `accessibility_connected`, `listener_connected`, `queue_size`, `last_error`, `app_version`, … |
| ← server | `GET /commands?device_id=` | `{"commands": [{id, type, args}]}` |
| ← server | `GET /files/<id>` | bytes for a `share_file` command |

The phone keeps events in a SQLite outbox and deletes them only after a 2xx, so the server must
deduplicate by `event_id` (it does).

## Events

| `type` | `payload` |
|---|---|
| `notification` | Raw WeCom notification: `chat`, `title`, `text`, `big_text`, `ticker`, `mentioned`, `can_reply`, `post_time`, … |
| `command_result` | `command_id`, `type`, `ok`, `error`, `message`, plus `screen` (for `snapshot`), `quoted` (for `reply_quote`), `screen_on_error` |
| `ui_dump` | Full accessibility tree of the current WeCom screen (recon mode) |

## Commands

Every command may carry `args.expires_at` (ms). Expired commands are not executed: a "got it"
two hours late is worse than none.

| `type` | `args` | What the phone does |
|---|---|---|
| `snapshot` | `chat` | Open the chat (via its notification intent), read all visible text |
| `send_text` | `chat`, `text` | Open the chat, verify the title, type, tap 发送, confirm the input box cleared |
| `reply_quote` | `chat`, `quote_key`, `text` | Find the bubble whose normalised text equals `quote_key` (scroll up ≤ 5 pages), long-press → 引用, then send. Falls back to a plain send and reports `quoted: false` |
| `share_file` | `chat`, `path`, `filename`, `caption` | Download `path`, share it to WeCom, pick the chat whose name matches exactly and uniquely, re-check the name in the confirm dialog, send |
| `dump` / `home` | – | Export the current screen / go to the home screen |

Commands are never re-sent automatically. If a result never arrives the server alerts a human.

## Text normalisation

`quote_key` is the bubble text with every character in `NORM_WS` collapsed to one space and trimmed.
The list is spelled out in both `server/wecomdroid/text.py` and `BotAccessibilityService.kt`
(Python and Kotlin disagree on what `\s` means, e.g. U+3000). A test fails if they differ.
