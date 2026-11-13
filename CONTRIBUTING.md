# Contributing

Issues and PRs are welcome, especially compatibility reports for different phones and WeCom versions
(see [docs/adapting.md](docs/adapting.md) for what to attach).

```bash
pip install -e "server[ai,dev]" && (cd server && pytest -q)    # server
cd android && ./gradlew assembleDebug                           # app (JDK 17, Android SDK 34)
```

Out of scope, and PRs adding them will be closed: mass messaging, auto-adding contacts,
auto-creating or auto-inviting to groups, bulk DMs, anything that bypasses WeCom's limits.
SpareDroid answers when it is asked. That is the line that keeps it useful and keeps accounts alive.
