package io.github.tonieeie.sparedroid

import android.content.Context
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * 执行服务器下发的指令。单线程串行：同一时刻只有一个指令在操作企业微信界面，
 * 两个指令同时点来点去必然出事。
 *
 * 指令格式（服务器 GET /commands 返回）：
 *   {"id": "...", "type": "send_text", "args": {"chat": "群名", "text": "...", "expires_at": 毫秒}}
 *   {"id": "...", "type": "reply_quote", "args": {"chat": "群名", "quote_key": "原消息规范化文字", "text": "..."}}
 *                                                                  引用原消息回复（找不到原消息就普通发送）
 *   {"id": "...", "type": "share_file", "args": {"chat": "群名", "path": "files/xx", "filename": "报价单.pdf", "caption": "..."}}
 *                                                                  下载文件并经企业微信"分享→选群"发出
 *   {"id": "...", "type": "snapshot",  "args": {"chat": "群名"}}   打开会话并读出整屏文字
 *   {"id": "...", "type": "dump"}                                  导出当前界面完整控件树
 *   {"id": "...", "type": "home"}                                  回到桌面
 *
 * 每条指令执行完都回报一条 command_result 事件（成功或带错误码的失败）。
 */
object CommandRunner {
    private val exec = Executors.newSingleThreadExecutor()

    @Volatile var busy = false
        private set

    fun submit(ctx: Context, cmd: JSONObject) {
        val app = ctx.applicationContext
        exec.execute { run(app, cmd) }
    }

    /**
     * 通用动作，一步一个。全部只作用于受控应用（见 Config.apps）。
     *   {"do": "launch", "package": "com.x"}      打开应用
     *   {"do": "read"}                             读出当前屏幕的全部文字 → result.screen
     *   {"do": "tap", "text": "确定"}              点文字 / 描述为「确定」的控件（"contains": true 时包含即可）
     *   {"do": "tap", "x": 540, "y": 1200}         点坐标
     *   {"do": "input", "text": "..."}             往输入框填字
     *   {"do": "scroll", "direction": "down"}      滚动
     *   {"do": "back"} / {"do": "home"}            返回 / 回桌面
     *   {"do": "wait", "ms": 800}                  等一下（最多 10 秒）
     */
    private fun step(svc: BotAccessibilityService, s: JSONObject, result: JSONObject) {
        when (val what = s.optString("do")) {
            "launch" -> svc.launch(s.getString("package"))
            "read" -> result.put("screen", svc.readScreen())
            "tap" -> if (s.has("x")) svc.tapAt(s.getInt("x"), s.getInt("y"))
                     else svc.tapText(s.getString("text"), s.optBoolean("contains", false))
            "input" -> svc.inputText(s.getString("text"))
            "scroll" -> svc.scroll(s.optString("direction", "down") != "up")
            "back" -> svc.back()
            "home" -> svc.goHome()
            "wait" -> Thread.sleep(s.optLong("ms", 500).coerceIn(0, 10_000))
            else -> throw CmdError("unknown_step", "不认识的动作：$what")
        }
        Thread.sleep(250) // 让界面跟上
    }

    /** 群里显示的文件名来自服务器；去掉路径符号和控制字符，防止写到共享目录外面。 */
    private fun safeFileName(raw: String): String {
        val s = raw.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_").trim().trimStart('.')
        if (s.isEmpty()) throw CmdError("bad_filename", "文件名为空")
        return s.take(120)
    }

    /** 分享过的文件留 7 天（企业微信可能稍后才读取），再久就删，文件不在手机上长期留存。 */
    private fun cleanOldFiles(dir: java.io.File) {
        val cutoff = System.currentTimeMillis() - 7L * 24 * 3600 * 1000
        dir.listFiles()?.filter { it.lastModified() < cutoff }?.forEach { it.delete() }
    }

    private fun run(ctx: Context, cmd: JSONObject) {
        val id = cmd.optString("id")
        val type = cmd.optString("type")
        val args = cmd.optJSONObject("args") ?: JSONObject()
        val result = JSONObject().put("command_id", id).put("type", type)
        Status.lastCommand = "$type $id"
        busy = true
        var touchedUi = false
        val svc = BotAccessibilityService.instance

        try {
            // 过期指令不执行：手机离线两小时后补发一句"收到"，比不发更糟。
            val expiresAt = args.optLong("expires_at", 0L)
            if (expiresAt > 0 && System.currentTimeMillis() > expiresAt) {
                throw CmdError("expired", "指令已过期，未执行")
            }
            if (svc == null) throw CmdError("a11y_off", "无障碍服务没开，无法操作企业微信")

            // 要动界面的指令：先确保屏幕亮着（黑屏时读得到界面、但填不了字）
            if (type in setOf("send_text", "reply_quote", "share_file", "snapshot", "run")) {
                result.put("woke_screen", svc.wakeScreen())
            }

            when (type) {
                "send_text" -> {
                    val chat = args.getString("chat")
                    val text = args.getString("text")
                    if (text.isBlank()) throw CmdError("empty_text", "要发送的内容为空")
                    if (text.length > 4000) throw CmdError("text_too_long", "内容超过 4000 字")
                    touchedUi = true
                    svc.openChat(chat)
                    svc.sendText(text, args.optString("send_label", "发送"))
                    result.put("chat", chat)
                }
                "reply_quote" -> {
                    // 引用原消息回复；找不到原消息时（默认）退回普通发送（回复内容应自带足够上下文，不引用也看得懂）
                    val chat = args.getString("chat")
                    val text = args.getString("text")
                    val key = args.getString("quote_key")
                    if (text.isBlank()) throw CmdError("empty_text", "要发送的内容为空")
                    touchedUi = true
                    svc.openChat(chat)
                    val why = svc.quoteMessage(key, args.optInt("max_pages", 5), args.optString("quote_label", "引用"))
                    result.put("chat", chat)
                    result.put("quoted", why == null)
                    if (why != null) {
                        result.put("quote_failed", why)
                        if (!args.optBoolean("fallback_plain", true)) throw CmdError("quote_failed", why)
                    }
                    svc.sendText(text, args.optString("send_label", "发送"))
                }
                "share_file" -> {
                    // 下载服务器上的文件（如 PDF），分享到指定会话；caption 作为留言一起发
                    val chat = args.getString("chat")
                    val path = args.getString("path") // 相对 endpoint，如 "files/ab12cd"
                    val name = safeFileName(args.getString("filename"))
                    val cfg = Config(ctx)
                    val dir = FileShareProvider.shareDir(ctx)
                    cleanOldFiles(dir)
                    val file = java.io.File(dir, name)
                    Http.download("${cfg.endpoint}/${path.trimStart('/')}", cfg.token, file)
                    result.put("chat", chat).put("filename", name).put("size", file.length())
                    touchedUi = true
                    val detail = svc.shareFile(file, chat, args.optString("caption").ifBlank { null },
                                               args.optString("package", WEWORK_PACKAGE),
                                               args.optString("send_label", "发送"))
                    result.put("share", detail)
                }
                "snapshot" -> {
                    val chat = args.getString("chat")
                    touchedUi = true
                    svc.openChat(chat)
                    Thread.sleep(500) // 等消息列表渲染完
                    result.put("chat", chat)
                    result.put("screen", svc.readScreen())
                }
                "dump" -> result.put("dump", svc.dumpTree())
                "home" -> svc.goHome()
                // 多步操作：按顺序做完一串通用动作（见 step），任何一步失败就停。
                // 一次指令做完，省掉每步 3 秒的轮询往返。return_home 默认 false —— 要回桌面就加一步 home。
                "run" -> {
                    val steps = args.getJSONArray("steps")
                    if (steps.length() > 40) throw CmdError("too_many_steps", "一次最多 40 步")
                    for (i in 0 until steps.length()) {
                        val s = steps.getJSONObject(i)
                        try {
                            step(svc, s, result)
                        } catch (e: CmdError) {
                            result.put("failed_step", i)
                            throw e
                        }
                    }
                    result.put("package", svc.foregroundPackage())
                }
                else -> throw CmdError("unknown_command", "不认识的指令类型：$type")
            }
            result.put("ok", true)
        } catch (e: CmdError) {
            result.put("ok", false).put("error", e.code).put("message", e.message)
            // 失败时顺手带上当前界面，服务器那边能看出卡在哪
            runCatching { svc?.readScreen() }.getOrNull()?.let { result.put("screen_on_error", it) }
        } catch (e: Exception) {
            result.put("ok", false).put("error", "exception").put("message", e.toString())
        } finally {
            // 操作完回桌面：停在某个会话里时，那个会话的新消息不会再弹通知，就漏了。
            if (touchedUi && args.optBoolean("return_home", true)) {
                runCatching { svc?.goHome(); Thread.sleep(500) }
            }
            runCatching { svc?.releaseScreen() } // 放手，之后按系统设置自己熄屏
            busy = false
            EventQueue.get(ctx).enqueue("command_result", result, Config(ctx).deviceId)
        }
    }
}
