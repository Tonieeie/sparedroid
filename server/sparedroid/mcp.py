"""MCP server: give an AI assistant (Claude, Cursor, ...) hands and eyes on the phone.

    pip install "sparedroid[mcp]"
    sparedroid mcp            # stdio; run it where `sparedroid serve` runs (same data directory)

It does not talk to the phone itself. It queues commands in the same database the running
``sparedroid serve`` uses and waits for the phone's answer, so every safety rule still applies:
only allow-listed apps, only allow-listed chats, rate limits, nothing re-sent automatically.

Set ``SPAREDROID_MCP_READONLY=true`` to expose only the tools that look (no tapping, typing or sending).

Besides tools it offers two resources (``sparedroid://status``, ``sparedroid://notifications``) and
two prompts (``check_phone``: find out why the phone is not working; ``answer_mentions``: go through
recent @-mentions and draft replies for the user to approve).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .bot import Bot
from .config import Config
from .features import FeatureDisabled
from .store import Store

INSTRUCTIONS = """\
SpareDroid controls a real Android phone through its accessibility service.

- Call phone_status first: it tells you whether the phone is online, which apps you may use, and
  lists any problems with a fix for each. If it lists problems, tell the user before trying anything else.
- You can only see and operate the allow-listed apps. Other apps are invisible; do not try to reach them.
- Look before you act: read_screen, then tap / type_text using the exact text you saw.
- For a known sequence (open app, tap, type, read) use run_steps: one round trip instead of five.
- Actions are real and visible to other people (messages are sent, buttons are pressed).
  Do not send messages, submit forms, buy, delete or change settings unless the user asked for exactly that.
- Each call takes a few seconds (the phone polls for work). If a call times out, do not blindly repeat
  an action that may already have happened; read the screen to find out.
"""


class Phone:
    """Queue a command for the phone and wait for its result. No MCP specifics in here."""

    def __init__(self, cfg: Config, store: Store, *, timeout_s: float = 45, poll_s: float = 0.4):
        self.cfg = cfg
        self.store = store
        self.bot = Bot(cfg, store, handler=lambda m, b: None)
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.readonly = os.environ.get("SPAREDROID_MCP_READONLY", "").lower() in ("1", "true", "yes")

    # -- plumbing ------------------------------------------------------------

    def _call(self, fn, *args, **kw) -> dict:
        try:
            return self._sent(self.wait(fn(*args, **kw)))
        except FeatureDisabled as exc:
            return {"ok": False, "error": f"feature_disabled: {exc}"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def wait(self, command_id: str) -> dict:
        if not command_id:
            return {"ok": False, "error": "rate_limited",
                    "message": "Reply rate limit reached for this chat; nothing was sent. Try again in a minute."}
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            cmd = self.store.command(command_id)
            if cmd and cmd["state"] in ("done", "failed"):
                return json.loads(cmd["result"] or "{}")
            if cmd and cmd["state"] in ("lost", "expired"):
                break
            time.sleep(self.poll_s)
        return {"ok": False, "error": "timeout",
                "message": f"No answer from the phone within {int(self.timeout_s)}s. It may be offline, locked, "
                           "or still working; check phone_status and read the screen before retrying."}

    def steps(self, steps: list[dict]) -> dict:
        try:
            return self._screen(self.wait(self.bot.run(steps, tag="mcp", ttl_s=int(self.timeout_s) + 15)))
        except FeatureDisabled as exc:
            return {"ok": False, "error": "feature_disabled", "message": str(exc)}
        except ValueError as exc:  # app outside the allow-list
            return {"ok": False, "error": "not_allowed_app", "message": str(exc)}

    @staticmethod
    def _screen(result: dict) -> dict:
        out = {"ok": bool(result.get("ok")), "app": result.get("package") or "", "texts": result.get("texts") or []}
        if result.get("screenshot"):
            out["screenshot"] = result["screenshot"]
        if not out["ok"]:
            out["error"] = f"{result.get('error')}: {result.get('message')}"
            if result.get("failed_step") is not None:
                out["failed_step"] = result["failed_step"]
        return out

    def _guard(self) -> dict | None:
        if self.readonly:
            return {"ok": False, "error": "readonly", "message": "SPAREDROID_MCP_READONLY is set: looking only."}
        return None

    def _chat_guard(self, chat: str) -> dict | None:
        if not self.cfg.works_in(chat):
            return {"ok": False, "error": "chat_not_allowed",
                    "message": f"「{chat}」 is not in SPAREDROID_CHATS; the bot may not send there."}
        return self._guard()

    # -- looking -------------------------------------------------------------

    def status(self) -> dict:
        last = float(self.store.get_meta("last_heartbeat") or 0)
        hb = json.loads(self.store.get_meta("last_heartbeat_body") or "{}")
        age = int(time.time() - last) if last else None
        return {
            "online": age is not None and age < 180,
            "last_heartbeat_seconds_ago": age,
            "can_read_and_act": bool(hb.get("accessibility_connected")),
            "can_hear_notifications": bool(hb.get("listener_connected")),
            "keep_alive": hb.get("keep_alive"),
            "phone_app_version": hb.get("app_version"),
            "allowed_apps": list(self.cfg.apps),
            "allowed_chats": sorted(self.cfg.chats),
            "features": sorted(self.cfg.features),
            "phone_features": hb.get("features"),
            "battery_level": hb.get("battery_level"),
            "plugged_in": hb.get("plugged"),
            "screen_locked": hb.get("keyguard_locked"),
            "readonly": self.readonly,
            "device": hb.get("device"),
            "problems": self.problems(hb, age),
            "last_app_restart": self.last_restart(),
        }

    @staticmethod
    def problems(hb: dict, age: int | None) -> list[str]:
        """What is wrong right now, each with the fix a person has to do on the phone."""
        if age is None:
            return ["The phone has never checked in. Install the app, import the config, and check the server URL."]
        out = []
        if age >= 180:
            out.append(f"No heartbeat for {age // 60} min: the phone is off, offline, or the app was killed. "
                       "Open SpareDroid on the phone.")
        if not hb.get("accessibility_connected"):
            out.append("Accessibility is " + ("switched OFF in system Settings - turn it back on"
                                              if hb.get("a11y_enabled") is False else "not connected - open the app")
                       + ". Without it nothing can be read or tapped.")
        if not hb.get("listener_connected"):
            out.append("Notification access is " + ("switched OFF in system Settings - turn it back on"
                                                    if hb.get("listener_enabled") is False
                                                    else "not connected - open the app")
                       + ". Without it new messages are not noticed.")
        if hb.get("keep_alive") is False:
            out.append("The keep-alive notification is gone; the system may stop the app while the screen is off.")
        if hb.get("keyguard_locked"):
            out.append("The screen is locked with a PIN / pattern; set the lock screen to None.")
        if hb.get("plugged") is False:
            out.append(f"The phone is not charging (battery {hb.get('battery_level')}%).")
        return out

    def last_restart(self) -> dict | None:
        raw = self.store.get_meta("last_app_start")
        if not raw:
            return None
        p = json.loads(raw)
        reasons = p.get("exit_reasons") or []
        crash = (p.get("crash") or "").splitlines()
        return {
            "phone_rebooted": (p.get("uptime_ms") or 0) < 15 * 60000,
            "crash": next((ln.strip() for ln in crash[2:] if ln.strip()), ""),
            "exit_reason": reasons[0].get("reason") if reasons else "",
            "last_alive": time.strftime("%Y-%m-%d %H:%M", time.localtime(p["last_alive_at"] / 1000))
            if p.get("last_alive_at") else "",
        }

    def notifications(self, limit: int = 20, app: str = "") -> list[dict]:
        return [{"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(n["at"])), "app": n["app"],
                 "chat": n["chat"], "title": n["title"], "text": n["text"], "mentioned": bool(n["mentioned"])}
                for n in self.store.recent_notifications(min(max(limit, 1), 100), app)]

    def mentions(self, limit: int = 20) -> list[dict]:
        return [{"id": m["id"], "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["at"])),
                 "chat": m["chat"], "sender": m["sender"], "text": m["text"]}
                for m in self.store.recent_messages(min(max(limit, 1), 100))]

    def read_screen(self, app: str = "") -> dict:
        steps = ([{"do": "launch", "package": app}, {"do": "wait", "ms": 1200}] if app else []) + [{"do": "read"}]
        return self.steps(steps)

    # -- acting --------------------------------------------------------------

    def act(self, *steps: dict) -> dict:
        """Do something, then read the screen so the caller sees the effect."""
        return self._guard() or self.steps([*steps, {"do": "wait", "ms": 700}, {"do": "read"}])

    LOOK_STEPS = frozenset({"read", "wait", "wait_for", "screenshot"})
    ALL_STEPS = LOOK_STEPS | {"launch", "tap", "input", "scroll", "back", "home", "long_press", "swipe",
                              "notify_action"}

    def run_steps(self, steps: list[dict]) -> dict:
        """Several steps in one round trip; always ends with a read so the caller sees the result."""
        if not steps or len(steps) > 20:
            return {"ok": False, "error": "bad_steps", "message": "Give 1 to 20 steps."}
        for i, st in enumerate(steps):
            if not isinstance(st, dict) or st.get("do") not in self.ALL_STEPS:
                return {"ok": False, "error": "bad_steps",
                        "message": f"step {i}: 'do' must be one of {sorted(self.ALL_STEPS)}"}
        if any(st["do"] not in self.LOOK_STEPS | {"launch"} for st in steps) and (g := self._guard()):
            return g
        if steps[-1]["do"] != "read":
            steps = [*steps, {"do": "wait", "ms": 600}, {"do": "read"}]
        return self.steps(steps)

    def screenshot(self, app: str = "") -> dict:
        steps = ([{"do": "launch", "package": app}, {"do": "wait", "ms": 1200}] if app else [])
        return self.steps(steps + [{"do": "screenshot"}, {"do": "read"}])

    def reply(self, message_id: str, text: str, quote: bool) -> dict:
        row = self.store.message(message_id)
        if row is None:
            return {"ok": False, "error": "unknown_message", "message": "No such message id; call recent_mentions."}
        return self._chat_guard(row["chat"]) or self._call(self.bot.reply, row["id"], text, quote=quote)

    def send(self, chat: str, text: str) -> dict:
        return self._chat_guard(chat) or self._call(self.bot.send, chat, text)

    def send_file(self, chat: str, path: str, caption: str) -> dict:
        if not Path(path).is_file():
            return {"ok": False, "error": "no_such_file", "message": path}
        return self._chat_guard(chat) or self._call(self.bot.send_file, chat, path, caption=caption)

    def send_image(self, chat: str, path: str, caption: str) -> dict:
        if not Path(path).is_file():
            return {"ok": False, "error": "no_such_file", "message": path}
        return self._chat_guard(chat) or self._call(self.bot.send_image, chat, path, caption=caption)

    @staticmethod
    def _sent(result: dict) -> dict:
        if result.get("ok"):
            return {"ok": True, **{k: result[k] for k in ("quoted", "method") if k in result}}
        return {"ok": False, "error": f"{result.get('error')}: {result.get('message')}"}


def build(phone: Phone):
    """Create the MCP server. Imported lazily so the core package works without the mcp dependency."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer("sparedroid", instructions=INSTRUCTIONS)
    # Hints let clients auto-approve looking and ask before acting. Everything touches a real phone.
    look = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    act = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
    send = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                           open_world_hint=True)

    @server.tool(annotations=look)
    def phone_status() -> dict:
        """Is the phone online, which apps and chats may be used, and is this session read-only? Call this first."""
        return phone.status()

    @server.tool(annotations=look)
    def read_screen(app: str = "") -> dict:
        """Read all visible text on the phone's screen, top to bottom.

        app: optional Android package name from allowed_apps; if given, that app is opened first.
        Returns {ok, app, texts}. Only allow-listed apps can be read.
        """
        return phone.read_screen(app)

    @server.tool(annotations=look)
    def screenshot(app: str = ""):
        """Take a screenshot of the phone (Android 11+; needs the 'screenshot' feature on server and phone).

        app: optional package name from allowed_apps to open first. Returns the image plus the screen text.
        Only allow-listed apps are ever captured.
        """
        from mcp.server.mcpserver import Image

        out = phone.screenshot(app)
        if not out.get("ok") or not out.get("screenshot"):
            return out
        return [Image(path=out["screenshot"]), {"app": out["app"], "texts": out["texts"]}]

    @server.tool(annotations=look)
    def recent_notifications(limit: int = 20, app: str = "") -> list[dict]:
        """Recent notifications the phone received from allow-listed apps, newest first."""
        return phone.notifications(limit, app)

    @server.tool(annotations=look)
    def recent_mentions(limit: int = 20) -> list[dict]:
        """Chat messages that @-mentioned the bot account, newest first. Use the id with reply_to_message."""
        return phone.mentions(limit)

    @server.tool(annotations=act)
    def tap(text: str, contains: bool = False) -> dict:
        """Tap the control whose text (or accessibility label) equals `text`; contains=true matches a substring.

        Returns the screen after the tap. Use text exactly as read_screen showed it.
        """
        return phone.act({"do": "tap", "text": text, "contains": contains})

    @server.tool(annotations=act)
    def type_text(text: str) -> dict:
        """Type into the input field on screen (the only one, or the focused one). Returns the screen afterwards."""
        return phone.act({"do": "input", "text": text})

    @server.tool(annotations=act)
    def scroll(direction: str = "down") -> dict:
        """Scroll the main list: "down" shows later content, "up" earlier. Returns the screen afterwards."""
        return phone.act({"do": "scroll", "direction": "up" if direction == "up" else "down"})

    @server.tool(annotations=act)
    def long_press(text: str, contains: bool = False) -> dict:
        """Long-press the control showing `text` (opens context menus). Returns the screen afterwards."""
        return phone.act({"do": "long_press", "text": text, "contains": contains})

    @server.tool(annotations=act)
    def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> dict:
        """Swipe from (x1, y1) to (x2, y2) in screen pixels over `ms` milliseconds. Returns the screen afterwards."""
        return phone.act({"do": "swipe", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "ms": ms})

    @server.tool(annotations=look)
    def wait_for_text(text: str, timeout_seconds: int = 8) -> dict:
        """Wait until `text` appears on screen (e.g. after loading or sending). Returns the screen."""
        return phone.steps([{"do": "wait_for", "text": text, "timeout_ms": timeout_seconds * 1000}, {"do": "read"}])

    @server.tool(annotations=act)
    def tap_notification_button(chat: str, button: str) -> dict:
        """Press a button on the latest notification from `chat` (e.g. "Mark as read"), without opening the app.

        recent_notifications lists the chats; the available buttons show up in the error if `button` is wrong.
        """
        return phone._guard() or phone.steps([{"do": "notify_action", "chat": chat, "action": button}])

    @server.tool(annotations=act)
    def run_steps(steps: list[dict]) -> dict:
        """Run up to 20 UI steps in one go and return the screen at the end. Faster than one tool per step.

        Each step is an object with "do" plus its arguments:
          {"do": "launch", "package": "<allowed app>"}   {"do": "read"}
          {"do": "tap", "text": "OK"} (or "contains": true, or "x"/"y" pixels)
          {"do": "input", "text": "hello"}               {"do": "scroll", "direction": "down"}
          {"do": "long_press", "text": "..."}            {"do": "swipe", "x1":, "y1":, "x2":, "y2":, "ms": 300}
          {"do": "wait", "ms": 800}                      {"do": "wait_for", "text": "Done", "timeout_ms": 8000}
          {"do": "back"}  {"do": "home"}                 {"do": "screenshot"}
        If a step fails, the result says which one (failed_step, 0-based) and shows the screen at that moment.
        """
        return phone.run_steps(steps)

    @server.tool(annotations=act)
    def press_back() -> dict:
        """Press the Android back button. Returns the screen afterwards."""
        return phone.act({"do": "back"})

    @server.tool(annotations=act)
    def go_home() -> dict:
        """Go to the phone's home screen (do this when you are finished with an app)."""
        return phone._guard() or phone.steps([{"do": "home"}])

    @server.tool(annotations=send)
    def reply_to_message(message_id: str, text: str, quote: bool = True) -> dict:
        """Reply in the chat to a message from recent_mentions. quote=true attaches the reply to that message.

        This sends a real message that other people will see.
        """
        return phone.reply(message_id, text, quote)

    @server.tool(annotations=send)
    def send_message(chat: str, text: str) -> dict:
        """Send a text message to an allowed chat (it must have messaged the bot since the phone app started).

        This sends a real message that other people will see.
        """
        return phone.send(chat, text)

    @server.tool(annotations=send)
    def send_image(chat: str, path: str, caption: str = "") -> dict:
        """Send an image (png / jpg / gif / webp) from this machine to an allowed chat; it shows as a picture.

        This sends a real message that other people will see.
        """
        return phone.send_image(chat, path, caption)

    @server.tool(annotations=send)
    def send_file(chat: str, path: str, caption: str = "") -> dict:
        """Send a file from this machine to an allowed chat, with an optional caption. Other people will see it."""
        return phone.send_file(chat, path, caption)

    @server.resource("sparedroid://status", name="phone-status", mime_type="application/json",
                     description="Same as the phone_status tool: online, permissions, problems, last restart.")
    def status_resource() -> str:
        return json.dumps(phone.status(), ensure_ascii=False, indent=1)

    @server.resource("sparedroid://notifications", name="recent-notifications", mime_type="application/json",
                     description="The 50 most recent notifications from allow-listed apps.")
    def notifications_resource() -> str:
        return json.dumps(phone.notifications(50), ensure_ascii=False, indent=1)

    @server.prompt(title="Check the phone")
    def check_phone() -> str:
        """Find out whether the SpareDroid phone is healthy and what to fix if not."""
        return ("Call phone_status. Explain in plain words whether the phone can currently hear new messages "
                "and act on them. For each item in `problems`, say what the person has to do on the phone. "
                "If `last_app_restart` is set, explain how the app ended last time (crash, killed by the system, "
                "or the phone rebooted) and what usually prevents it (battery optimisation off, keep the app "
                "locked in recent apps, keep the phone plugged in). Do not tap or send anything.")

    @server.prompt(title="Answer recent mentions")
    def answer_mentions(limit: int = 10) -> str:
        """Go through recent @-mentions of the bot and draft replies; send only what the user approves."""
        return (f"Call recent_mentions with limit={limit}. For each message, draft a short reply. Show all drafts "
                "to me in a numbered list and wait. Only after I approve a draft, send it with reply_to_message "
                "(quote=true). Never send a draft I did not approve, and never send the same reply twice.")

    return server


def main() -> None:
    cfg = Config.from_env()
    phone = Phone(cfg, Store(cfg.data_dir / "sparedroid.db"))
    build(phone).run()
