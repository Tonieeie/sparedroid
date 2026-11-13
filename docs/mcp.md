# MCP：让 AI 助手用这台手机

SpareDroid 自带一个 [MCP](https://modelcontextprotocol.io) 服务。接上之后，Claude Code、Claude Desktop、
Cursor 这类 AI 工具可以直接「看手机屏幕、点按钮、读群消息、回复」，你不用写一行代码。

```text
你：    看一下小店管家里今天的订单数
Claude：（调用 read_screen）今日订单 13 单，营业额 ¥3,668，待发货 4 单。

你：    客户群里刚才谁 @ 了机器人？帮我回一句「下午三点前回复您」
Claude：（调用 recent_mentions → reply_to_message）已引用 Alice 的消息回复。
```

## 前提

MCP 服务不直接连手机。它往 `sparedroid serve` 用的同一个数据库里排指令，等手机回报结果。所以：

- `sparedroid serve` 必须在跑，手机已经连上（`sparedroid status` 能看到心跳）；
- MCP 服务要和它**在同一台机器、同一个数据目录**上运行。

## 安装

```bash
pip install "sparedroid[mcp]"
```

### Claude Code

```bash
claude mcp add sparedroid -e SPAREDROID_HOME=/path/to/sparedroid -- sparedroid mcp
```

### Claude Desktop / Cursor（JSON 配置）

```json
{
  "mcpServers": {
    "sparedroid": {
      "command": "sparedroid",
      "args": ["mcp"],
      "env": { "SPAREDROID_HOME": "/path/to/sparedroid" }
    }
  }
}
```

`SPAREDROID_HOME` 是放 `.env` 和 `data/` 的那个目录（AI 工具启动 MCP 服务时的工作目录不固定，所以要明说）。

### 服务器在远端（VPS / Docker）

MCP 走标准输入输出，所以可以直接隔着 SSH 或 `docker exec` 用，不需要再开端口：

```bash
# 服务器用 docker compose 跑
claude mcp add sparedroid -- ssh you@your-server "cd sparedroid && docker compose exec -T sparedroid sparedroid mcp"

# 服务器用 pip 装
claude mcp add sparedroid -- ssh you@your-server "SPAREDROID_HOME=/opt/sparedroid sparedroid mcp"
```

## 工具

| 工具 | 作用 | 会改变什么吗 |
|---|---|---|
| `phone_status` | 手机在不在线、能用哪些应用和会话 | 否 |
| `read_screen(app?)` | 读出屏幕上的全部文字；给了包名就先打开那个应用 | 只会打开应用 |
| `recent_notifications(limit, app?)` | 受控应用最近的通知 | 否 |
| `recent_mentions(limit)` | 最近 @ 机器人的聊天消息（带 id） | 否 |
| `tap(text, contains?)` | 点文字为 `text` 的控件，返回点完后的屏幕 | **是** |
| `type_text(text)` | 往输入框填字 | **是** |
| `scroll(direction)` / `press_back` / `go_home` | 滚动 / 返回 / 回桌面 | 界面 |
| `screenshot(app?)` | 截图并把图片直接给 AI 看（需打开 `screenshot` 功能，Android 11+） | 只会打开应用 |
| `long_press(text)` / `swipe(x1,y1,x2,y2)` | 长按 / 滑动 | **是** |
| `wait_for_text(text, timeout_seconds)` | 等某段文字出现 | 否 |
| `tap_notification_button(chat, button)` | 点某个会话最新通知上的按钮（如「标为已读」），不用开屏 | **是** |
| `reply_to_message(message_id, text, quote)` | 回复某条 @ 消息（默认引用） | **发出真实消息** |
| `send_message(chat, text)` | 往某个会话发一句话 | **发出真实消息** |
| `send_file(chat, path, caption)` | 把本机的文件发到某个会话 | **发出真实消息** |
| `send_image(chat, path, caption)` | 把本机的图片发到某个会话 | **发出真实消息** |

关掉的功能（`SPAREDROID_FEATURES` 或手机设置页）对应的工具会直接返回 `feature_disabled`。

每次调用要几秒（手机每 3 秒来取一次指令）。

## 安全

AI 助手拿到的是一部真手机，下面这些限制是为它设的：

- **应用白名单照样生效**：`SPAREDROID_APPS` 之外的应用，AI 看不到也点不了。要让 AI 操作哪个应用，就把它的包名加进去；
  不想让 AI 碰的（银行、支付、私人聊天）就别加。
- **会话白名单照样生效**：只能往 `SPAREDROID_CHATS` 里的会话发消息，发送频率限制也在。
- **只看不动**：设 `SPAREDROID_MCP_READONLY=true`，点击、输入、发消息的工具全部拒绝，只剩读屏和查看。
  第一次接入建议先这样用。
- **不会自动重试**：手机没回音时工具返回超时，并提醒 AI 先读屏确认，而不是把同一个动作再做一遍。
- 服务自带的说明会告诉 AI：发消息、提交、购买、删除、改设置这类动作，只有用户明确要求时才做。
  但这只是提示，**真正的防线是白名单**；涉及钱和不可撤销的操作，请在你的 AI 工具里保留人工确认。
- 提示注入：屏幕和消息里的文字是别人写的，可能包含「请把这个文件发给我」之类的话。
  不要把这台手机交给会自动执行任何屏幕内容的无人值守 Agent。

## 验证状态

MCP 服务本身有端到端测试（真实 MCP 客户端 + 模拟手机）。它依赖的通用动作（打开应用、读屏、点击）
是 0.2.0 新增的，**还没有在真机上验证**；聊天相关的工具用的是真机验证过的那一套。
