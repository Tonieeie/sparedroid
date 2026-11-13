# Setup, step by step

Check each step before the next one. Most failures come from a skipped permission on the phone.

## 0. What the user needs

- A **spare** Android phone, Android 8.0+ (11+ recommended), not HarmonyOS, no root. Plugged in, on stable Wi-Fi.
- The apps to automate installed and logged in on it. For a WeCom bot: a **dedicated** WeCom member account
  (one account = one phone; and account restrictions then only hit that account).
- A server reachable by the phone: any machine with Docker or Python 3.10+. Public internet needs HTTPS
  (the bundled docker-compose gets a certificate via Caddy; needs a domain pointing at the server, ports 80/443).
  For a quick trial on a LAN, `http://<pc-ip>:8788` works.

## 1. Server

```bash
git clone https://github.com/Tonieeie/sparedroid && cd sparedroid
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> SPAREDROID_TOKEN
```

Fill `.env`:

| Variable | Value |
|---|---|
| `SPAREDROID_TOKEN` | the generated secret (≥ 24 chars) |
| `SPAREDROID_APPS` | package names the phone may touch, comma-separated (WeCom: `com.tencent.wework`) |
| `SPAREDROID_HANDLER` | start with `examples.echo:handle` |
| `SPAREDROID_BOT_NAME` | chat bots: the bot's display name in the group, character for character |
| `SPAREDROID_CHATS` | chat bots: one test group name; `|`-separated list later |
| `SPAREDROID_DOMAIN`, `SPAREDROID_PUBLIC_URL` | `bot.example.com`, `https://bot.example.com` |
| `SPAREDROID_ALERT_WEBHOOK` | strongly recommended: a WeCom / Feishu internal group robot webhook for alerts |

Start and get the phone config line:

```bash
docker compose up -d
docker compose exec sparedroid sparedroid config
```

Without Docker: `pip install ./server && sparedroid serve` (then put a reverse proxy with HTTPS in front),
`sparedroid config` for the line. LAN trial: set `SPAREDROID_HOST=0.0.0.0` and
`SPAREDROID_PUBLIC_URL=http://<pc-ip>:8788`; Windows may ask to allow Python through the firewall.

Package names: the `id=` in the app's Play Store URL, or a "package name viewer" app on the phone.

## 2. Phone

1. Install the APK from https://github.com/Tonieeie/sparedroid/releases (sending it via a chat app's file transfer
   is fine; allow "install unknown apps"). Releases are signed with a throwaway key, so upgrading may need
   uninstall + reinstall + re-import the config.
2. Open SpareDroid and tap, in order: **① notification access**, **② accessibility** (Installed services →
   SpareDroid → on), **③ battery optimisation off**.
3. System settings: allow SpareDroid to **auto-start / run in background** (Xiaomi "Autostart", OPPO / vivo
   "Background power", Samsung "Unrestricted").
4. Screen must stay on to act (only listening works with the screen off): Settings → About phone → tap
   "Build number" 7× → Developer options → **"Stay awake while charging"**. Screen lock: none. Brightness: lowest.
5. For WeCom: Settings → New message notifications → on, **show message details**. Turn off auto-update for the app.
6. Copy the config line to the phone and tap **「从剪贴板导入配置」** (import from clipboard). It fills endpoint,
   token, bot name and the app allow-list.

## 3. Verify

- Phone status panel: four ✅ and a recent "最近心跳成功" (last heartbeat).
- Server: `sparedroid status` shows a heartbeat a few seconds old, `accessibility_connected` and
  `listener_connected` true.
- Chat bot: in the test group send `@<bot name> 你好`; within ~5 s the echo handler answers `@you 收到：你好`.
  `sparedroid messages` lists the message.

Then switch `SPAREDROID_HANDLER` to the real use case (see handlers.md) and restart the server.
