# Troubleshooting

Start with `sparedroid status` on the server and the status panel in the phone app. Then follow the symptom.

## The bot doesn't react to @-mentions

Check in this order — each step depends on the previous one:

1. **Heartbeat.** `sparedroid status` shows a heartbeat older than a minute or "never" → the phone can't reach the
   server. Check the endpoint and token in the app, HTTPS certificate, firewall / cloud firewall, phone network.
   The app's "最近错误" (last error) usually names it (timeout, 401/404, certificate).
2. **Notification listener.** `listener_connected: false` (common right after reinstalling) → in the app tap
   ① notification access, switch SpareDroid **off and on again**, or reboot the phone.
3. **Allow-lists.** The chat name must be in `SPAREDROID_CHATS` exactly (WeCom may add a member count in the title
   bar, but the notification title is the bare name). The app's package must be in the phone's app list.
4. **Bot name.** WeCom does not always add "[有人@我]" to notifications; then the @ is recognised only by
   `SPAREDROID_BOT_NAME` (server) and the bot name in the app. Both must match the group display name exactly.
5. **App notifications.** In WeCom: new message notifications on, message details shown.
6. **The message scrolled away.** The server reads the screen and answers only the bubble that triggered the
   notification; if it can't find it (busy group), it stays silent on purpose. Log line: "could not find …".

## Error codes from the phone

| Code | Meaning | Fix |
|---|---|---|
| `no_route` | the app can't open that chat: no notification from it since the app (re)started | wait for the next message in that chat; files are unaffected |
| `chat_not_opened` | opened something, but the title / input box didn't match | screen dump in `data/dumps/*error_screen*`; may need adapting |
| `not_target_app` / `not_allowed_app` | foreground app is not allow-listed | add the package to the app list (if appropriate) |
| `no_input` | no unique input box (voice-input mode, or several boxes) | switch the chat to keyboard input |
| `no_send_button` | no button labelled 发送 | other app / language: set `SPAREDROID_SEND_LABEL` |
| `send_unconfirmed` | tapped send, input box didn't clear | check the chat by hand; **not** retried automatically to avoid double sends |
| `no_quote_menu` / `quoted: false` | quote failed; a plain reply was sent instead | normal fallback; set `SPAREDROID_QUOTE_LABEL` for other apps |
| `picker_not_shown` / `chat_not_found` / `chat_ambiguous` | file sharing couldn't pick exactly one chat by name | chat names must be unique and unchanged |
| `feature_disabled` | switched off on the server (`SPAREDROID_FEATURES`) or on the phone (settings → 功能开关) | turn it on in both places |
| `screen_locked` | phone sits on a lock screen | set screen lock to "none" |
| `no_quick_reply` | the chat's notification has no reply button | normal; plain replies fall back to the UI automatically |
| `unsupported` (screenshot) | Android 10 or older | screenshots need Android 11+ |
| `not_found` (run step) | no control with that text | `read` first and use the exact text |
| `timeout` (MCP) | no result within the wait | phone offline, locked or busy; read the screen before retrying |

## Works, then stops after hours

Battery optimisation or the vendor's background killer. Re-check ③ in the app and the system "auto-start /
background" setting. If `SPAREDROID_ALERT_WEBHOOK` is set, the server reports "no heartbeat for N min".

## The screen went off and replies fail

Developer options → "Stay awake while charging", and screen lock "none". Listening still works with the screen
off; acting doesn't.

## A new app version broke something

Turn on **recon mode** (侦察模式) in the app, walk through the broken screens, turn it off. Accessibility trees land
in `data/dumps/`. Open an issue with app version, phone model, Android version and the dumps — after removing chat
content and personal data from them. Adapting code lives in `BotAccessibilityService.kt`.

## Upgrading the app fails ("app not installed")

Release APKs are signed with a throwaway key per build. Uninstall, install the new one, re-grant the three
permissions and re-import the config.
