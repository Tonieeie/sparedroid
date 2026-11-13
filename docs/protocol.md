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
| `notification` | Raw notification from an allow-listed app: `package`, `chat`, `title`, `text`, `big_text`, `ticker`, `mentioned`, `can_reply`, `post_time`, … |
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
| `run` | `steps: [...]` | Generic steps in any allow-listed app, stopping at the first failure: `launch {package}`, `read`, `tap {text[, contains]}` or `tap {x, y}`, `input {text}`, `scroll {direction}`, `back`, `home`, `wait {ms}`. Result carries `screen` (from the last `read`), `package`, and `failed_step` on error |
| `dump` / `home` | – | Export the current screen / go to the home screen |

`send_text`, `reply_quote` and `share_file` accept optional `send_label` / `quote_label` (button texts,
default 发送 / 引用) and `share_file` an optional `package`.

**Allow-list.** The phone holds a list of package names (settings page, or `apps` in the imported
config). Notifications from other apps are not forwarded, and every read / tap / input checks that the
foreground window belongs to a listed app, failing with `not_target_app` / `not_allowed_app` otherwise.

Commands are never re-sent automatically. If a result never arrives the server alerts a human.

## Text normalisation

`quote_key` is the bubble text with every character in `NORM_WS` collapsed to one space and trimmed.
The list is spelled out in both `server/wecomdroid/text.py` and `BotAccessibilityService.kt`
(Python and Kotlin disagree on what `\s` means, e.g. U+3000). A test fails if they differ.
