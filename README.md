<div align="center">

# SpareDroid

**把一台旧安卓手机，变成任何应用的「API」**

很多应用没有接口，或者接口不让你用（比如企业微信的外部群）。
SpareDroid 让一台闲置安卓手机替你盯着这些应用：**听它的通知、读它的屏幕、替你点和输入**，
而「看到什么该怎么办」写在你自己服务器上的几行 Python 里。

第一个、也是打磨得最完整的用例：**企业微信外部群里的 AI 客服 / 接单机器人**。

[English](README.en.md) · [需要准备什么](#你需要准备什么) · [安装](#安装) · [写你自己的逻辑](#写你自己的逻辑) · [接入 AI 助手（MCP）](docs/mcp.md) · [用例画廊](#用例画廊) · [常见问题](docs/faq.md)

![CI](https://github.com/Tonieeie/sparedroid/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Android](https://img.shields.io/badge/android-8.0%2B-green)

</div>

![SpareDroid](docs/media/hero.png)

## 它是什么

手机只会三件事，而且只对你点名的应用做：

| 手机做的事 | 靠什么 | 举例 |
|---|---|---|
| **听** | 安卓通知监听 | 群里有人 @ 机器人；店铺应用弹出「新订单」 |
| **读** | 安卓无障碍服务 | 读出聊天界面的整条消息；读出应用里「今日订单 13」 |
| **做** | 安卓无障碍服务 | 打开会话、输入、点发送、引用回复、分享文件、点任意按钮 |

你的服务器决定其余的一切：

```python
def handle(msg, bot):            # 有人在群里 @ 机器人
    return "收到～"

def on_notification(n, bot):     # 受控应用来了任何通知
    ...

def on_screen(screen, bot):      # 你让手机读的屏幕，读回来了
    ...
```

![架构](docs/architecture.svg)

**不 root、不 hook、不改任何应用**，用的是安卓官方给读屏软件准备的接口，代码全部开源可审计。
手机只和你自己的服务器通信。

## 你需要准备什么

### 一台安卓手机

| 项目 | 要求 | 说明 |
|---|---|---|
| 系统 | **Android 8.0 及以上**，推荐 11+ | 8/9 能用，但后台保活差一些 |
| 鸿蒙 | **不支持** HarmonyOS | 无障碍行为不同，未适配 |
| 是否 root | 不需要 | |
| 性能 | 没要求 | 几年前的千元机就够；App 本身不到 1 MB |
| 屏幕 | 要能**长期亮屏** | 「做」这一类动作需要屏幕亮着、不锁屏；只「听」不需要 |
| 供电 | **一直插着充电器** | |
| 网络 | 稳定的 WiFi（或流量） | 断网期间的消息会存在手机上，恢复后补传 |
| 用途 | **专用**，别用主力机 | 它会自己打开应用、点来点去 |

iPhone 不行（iOS 不允许应用读取其它应用的界面）。云手机 / 模拟器可以试，但聊天类应用容易识别出来。

### 手机上要开的权限

| 权限 | 用来做什么 | 不开会怎样 |
|---|---|---|
| **通知使用权** | 听受控应用的通知 | 完全收不到消息 |
| **无障碍服务** | 读屏幕、点击、输入 | 只能听，不能读整条消息、不能回复 |
| **忽略电池优化** + 自启动 / 后台运行 | 不被系统杀掉 | 跑几小时后静默掉线 |
| 开发者选项里的 **「充电时不锁屏」** | 屏幕常亮 | 熄屏后回复失败 |
| 联网 | 和你的服务器通信 | — |

App 不申请定位、通讯录、短信、相机、麦克风、存储权限。

### 要操作的应用和账号

- 把要操作的应用装在这台手机上并登录。**只有你在配置里列出包名的应用**，手机才会听、读、点；没列的一律不碰。
- 做聊天机器人时，用一个**专用账号**（企业微信就是一个专用的员工账号）。同一账号通常只能一台手机登录，而且自动化有被限制的风险，别用自己的号。
- 关掉该应用的**自动更新**，界面大改版后可能需要适配。

### 一台服务器

| 项目 | 要求 |
|---|---|
| 系统 | 任何能跑 Docker 或 Python 3.10+ 的机器（1 核 512 MB 足够） |
| 网络 | 手机要能访问到它。公网部署**必须用 HTTPS**；自带的 docker-compose 用 Caddy 自动申请证书，需要一个域名和 80/443 端口 |
| 只想先试试 | 手机和电脑连同一个 WiFi，直接用 `http://电脑IP:8788` 也行 |
| AI 用例 | 还需要一个 Claude API key |

### 已验证和未验证

| | 状态 |
|---|---|
| 企业微信：识别 @、读消息、回复、引用回复、发文件 | ✅ 真机验证（2026-11，一台安卓机） |
| 任意应用的通知转发 | ⚠️ 代码与测试完成，真机上只验证过企业微信的通知 |
| 任意应用的 `bot.run` 通用动作（打开 / 读屏 / 点击 / 输入 / 滚动） | ⚠️ 0.2.0 新增，通过编译和单元测试，**尚未真机验证** |
| MCP 服务（`sparedroid mcp`） | ✅ 端到端测试（真实 MCP 客户端 + 模拟手机）；依赖的通用动作同上，未真机验证 |
| 其它聊天应用的发消息 / 引用 | ⚠️ 需要设置按钮文字（`SPAREDROID_SEND_LABEL` 等），未验证 |

欢迎用 [兼容性反馈](https://github.com/Tonieeie/sparedroid/issues/new/choose) 告诉我们你的机型和应用。

## 安装

### 1. 服务器

```bash
git clone https://github.com/Tonieeie/sparedroid && cd sparedroid
cp .env.example .env
```

编辑 `.env`，至少填这几项：

| 变量 | 填什么 |
|---|---|
| `SPAREDROID_TOKEN` | 手机和服务器之间的口令，至少 24 位。生成：`python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SPAREDROID_APPS` | 受控应用的包名，逗号分隔。默认 `com.tencent.wework`（企业微信） |
| `SPAREDROID_HANDLER` | 用哪段逻辑。先用 `examples.echo:handle` 测通 |
| `SPAREDROID_BOT_NAME` | （聊天机器人）机器人在群里显示的名字，必须一字不差 |
| `SPAREDROID_CHATS` | （聊天机器人）在哪些群里工作，`|` 分隔；`*` 表示所有群 |
| `SPAREDROID_DOMAIN` / `SPAREDROID_PUBLIC_URL` | 你的域名，如 `bot.example.com` / `https://bot.example.com` |
| `SPAREDROID_ALERT_WEBHOOK` | （强烈建议）一个内部群机器人的 webhook，手机掉线、消息没发出去时通知你 |

```bash
docker compose up -d
docker compose exec sparedroid sparedroid config    # 打印一行配置，手机上要用
```

不用 Docker：`pip install ./server && sparedroid serve`，自己配反向代理和 HTTPS。

> 怎么查应用的包名：应用商店网页版链接里的 `id=` 后面那串；或者手机上装一个「包名查看器」。
> 常见的：企业微信 `com.tencent.wework`。

### 2. 手机

1. 安装并登录要操作的应用（做企业微信机器人：登录机器人账号，把它拉进一个测试群）。
2. 安装 SpareDroid：从 [Releases](https://github.com/Tonieeie/sparedroid/releases) 下载 APK，或自己编译（`cd android && ./gradlew assembleDebug`，需要 JDK 17）。
3. 打开 SpareDroid，依次点三个按钮：**① 通知使用权**、**② 无障碍**、**③ 关闭省电限制**。
4. 系统设置里允许它**自启动 / 后台运行**；开发者选项里打开**「充电时不锁屏」**；锁屏方式设为「无」。
5. 把服务器打印的那行配置发到手机上（比如用微信文件传输助手），复制，点 **「从剪贴板导入配置」**。
6. 状态面板出现四个 ✅、「最近心跳成功」有时间，就连上了。

每一步的截图级说明和各品牌手机的差异见 [docs/phone-setup.md](docs/phone-setup.md)。

### 3. 试一下

在测试群里发 `@机器人 你好`，几秒后它回 `@你 收到：你好`。
服务器上 `sparedroid status` 能看到手机心跳，`sparedroid messages` 能看到收到的消息。

## 写你自己的逻辑

在一个 Python 文件里写下面任意几个函数，把 `SPAREDROID_HANDLER` 指向它（如 `my_handler:handle`）。

| 你写的函数 | 什么时候被调用 |
|---|---|
| `handle(msg, bot)` | 聊天里有人 @ 机器人。返回文字就是回复，返回 `None` 不回 |
| `on_notification(n, bot)` | 受控应用来了**任何**通知（不限聊天） |
| `on_screen(screen, bot)` | 你用 `bot.run([...])` 让手机做的事做完了，屏幕文字读回来了 |
| `on_tick(bot)` | 大约每 30 秒一次，用来做定时任务 |

| 你能让手机做的 | |
|---|---|
| `return "文字"` / `return Reply(text, quote=True)` | 回复 / 引用原消息回复 |
| `bot.reply(msg_id, text, quote=True)` | 以后再回某条消息（比如订单处理完） |
| `bot.send(chat, text)` | 往某个会话发一句话 |
| `bot.send_file(chat, path, caption=...)` | 把文件发到某个会话 |
| `bot.run(steps, tag=...)` | 在任意受控应用里执行一串通用动作（见下表） |
| `bot.alert(text)` | 通知你的团队 |

`bot.run` 的动作：

| 动作 | 作用 |
|---|---|
| `{"do": "launch", "package": "com.x"}` | 打开应用 |
| `{"do": "read"}` | 读出当前屏幕的全部文字 |
| `{"do": "tap", "text": "确定"}` | 点文字为「确定」的控件（加 `"contains": true` 则包含即可；也可用 `"x"`/`"y"` 点坐标） |
| `{"do": "input", "text": "..."}` | 往输入框填字 |
| `{"do": "scroll", "direction": "down"}` | 滚动 |
| `{"do": "back"}` / `{"do": "home"}` / `{"do": "wait", "ms": 800}` | 返回 / 回桌面 / 等一下 |

```python
# 例：每 10 分钟打开店铺应用，读「今日订单」
def on_tick(bot):
    bot.run([{"do": "launch", "package": "com.example.shop"},
             {"do": "tap", "text": "数据"},
             {"do": "read"}, {"do": "home"}], tag="sales")

def on_screen(screen, bot):
    if screen.tag == "sales" and screen.ok:
        print(screen.texts)          # ['今日订单', '13', '今日营业额', '¥3,668', ...]
```

命令行也能直接用：`sparedroid messages`、`sparedroid reply <id> "…" --quote`、`sparedroid send-file <会话> <文件>`。

## 让 AI 助手直接用这台手机（MCP）

不想写代码？SpareDroid 自带 MCP 服务，Claude Code、Claude Desktop、Cursor 接上就能「看屏幕、点按钮、读群消息、回复」：

```bash
pip install "sparedroid[mcp]"
claude mcp add sparedroid -e SPAREDROID_HOME=/path/to/sparedroid -- sparedroid mcp
```

```text
你：    看一下小店管家里今天的订单数
Claude：（read_screen）今日订单 13 单，营业额 ¥3,668，待发货 4 单。
```

应用白名单、会话白名单、频率限制照样生效；`SPAREDROID_MCP_READONLY=true` 可以让 AI 只看不动。
工具列表、远程用法和安全说明见 [docs/mcp.md](docs/mcp.md)。

## 安全边界

- **应用白名单**：手机只听、只读、只点 `SPAREDROID_APPS` 里列出的应用。没列出的（银行、支付、私人聊天）它看不到也不会碰。别把你不愿意把屏幕内容交给服务器的应用列进去。
- **只用在你自己的手机和账号上。** 这是把你自己的设备自动化，不是读别人手机的工具；App 有常驻状态面板，不隐藏自己。
- **聊天场景只在被 @ 时回应**，自带频率限制。刻意不做群发、自动加好友、自动拉群 —— 那是发广告的功能，也是封号的主要原因。
- **认不出界面就停手**，不猜着点；发消息前核对会话名，发完确认发出；不确定的一律报给人，不自动重发。
- 聊天应用可能限制自动化账号，**没有任何方案能保证不封号**。专用账号、保持默认频率、先小范围试。

## 它是怎么工作的

以企业微信群里的一次问答为例：

1. 有人 @ 机器人 → 企业微信弹系统通知 → App 的通知监听拿到它，交给服务器。
2. 通知里的字会被截断，所以服务器让手机**打开那个群、读出整屏文字**，只认触发的那一条。
3. 你的 `handle()` 决定回什么。
4. 服务器排一条指令；手机取走，填字、点发送，确认输入框清空才算成功。

设计原则是**手机越笨越好**：应用改版时，只要手机还能读字和点字，就只改服务器上的 Python。
App 带**侦察模式**，能把任意受控应用的界面结构导出来，适配新应用或新版本时用，见 [docs/adapting.md](docs/adapting.md)。
协议细节见 [docs/protocol.md](docs/protocol.md)。

## 路线图

- [ ] 真机录屏演示；更多机型和应用的兼容性验证
- [ ] 界面定位规则改成服务器下发，适配新版本不用重编译 App
- [x] MCP 服务：让 Claude / Cursor 等 AI 工具直接「看手机屏幕、操作应用」（[docs/mcp.md](docs/mcp.md)）
- [ ] Claude Code skill：一步步带你把手机和服务器配好
- [ ] 回复前自动点亮屏幕

欢迎 issue 和 PR。范围之外的功能（群发、批量加人等）见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 用例画廊

每个用例都是 `examples/` 里一个可以直接跑的文件。<sub>动图为示意动画（界面经过简化，不是真实应用截图）。</sub>

### 1. 企业微信 AI 客服

客户在外部群里 @ 机器人提问，Claude **只根据你的知识库**回答；答不了的不硬编，回复「请同事确认」并通知你的团队。

![AI 客服](docs/media/demo-ai.gif)

```bash
SPAREDROID_HANDLER=examples.claude_qa:handle
ANTHROPIC_API_KEY=sk-ant-...
SPAREDROID_KNOWLEDGE=你的知识库.md
```

### 2. 群里格式化接单

客户按模板在群里下单 → 校验字段 → 写进表格 → 回复「收到」。处理完（几小时、几天后）引用原消息回结果，还能把文件发回原来的群。

![接单](docs/media/demo-order.gif)

```bash
SPAREDROID_HANDLER=examples.order_intake:handle
# 处理完之后：
sparedroid reply <消息ID> "张三的订单已完成：https://…" --quote
sparedroid send-file <群名> 报价单_张三.pdf
```

这个项目就是从这个场景里长出来的：渠道在企业微信外部群里发保险订单，原来要人工抄进表格。

### 3. 把没有接口的应用接进你的系统

店铺应用弹了「新订单」→ 转发到团队群。每 10 分钟打开应用、读出「今日订单」→ 数字变了就通知或写表。

![任意应用](docs/media/demo-any.gif)

```bash
SPAREDROID_APPS=com.example.shop
SPAREDROID_HANDLER=examples.notify_forward     # 通知 → webhook
SPAREDROID_HANDLER=examples.screen_watch       # 定时读屏，数值变化时提醒
```

### 4. 关键词 FAQ（不用 AI）

改一个 JSON 文件就能用，零成本、回答完全可控。

```bash
SPAREDROID_HANDLER=examples.keyword_faq:handle
```

### 还能做什么

| 想法 | 用到的能力 |
|---|---|
| 物流 / 外卖 / 工单应用的状态变化 → 推到团队群 | `on_notification` |
| 只有 App 没有网页后台的系统，定时抄数据进表格 | `on_tick` + `bot.run` + `on_screen` |
| 群里 @ 机器人「查一下 XX」→ 手机去另一个应用里查 → 回到群里答复 | `handle` + `bot.run` + `bot.reply` |
| 给你的 AI Agent 一部手机：让它看屏幕、点按钮 | `sparedroid mcp`（见 [docs/mcp.md](docs/mcp.md)） |
| 监控某个应用里的排队号、库存、价格 | `examples/screen_watch.py` 改一行正则 |

## License

[MIT](LICENSE)。企业微信是腾讯的商标；本项目与腾讯及任何被操作的应用无关。
