package io.github.tonieeie.sparedroid

/**
 * 功能开关。手机这边关掉的功能，服务器发来指令也一律拒绝（feature_disabled）——
 * 服务器配置写错、或者服务器被人拿到口令时，手机是最后一道闸。
 *
 * 只管"做"的能力。"听"（通知监听）是核心，由受控应用白名单控制，不在这里。
 */
object Features {
    data class Feature(val key: String, val label: String, val hint: String, val default: Boolean)

    val ALL = listOf(
        Feature("reply", "回复文字", "在会话里发文字消息", true),
        Feature("quote", "引用回复", "长按原消息 → 引用后回复", true),
        Feature("quick_reply", "通知快捷回复", "用通知上的「回复」按钮直接回，不用开屏、不用打开应用", true),
        Feature("files", "发文件", "经「分享 → 选会话」发文件", true),
        Feature("images", "发图片", "经「分享 → 选会话」发图片", true),
        Feature("read", "读屏", "读出受控应用屏幕上的文字", true),
        Feature("control", "操作应用", "打开应用、点击、输入、滚动、长按、滑动、点通知按钮", true),
        Feature("screenshot", "截图", "把受控应用的画面截图传给服务器（Android 11+）。画面里可能有隐私，默认关闭", false),
        Feature("wake_screen", "自动亮屏", "动界面前点亮屏幕，做完让它自己熄灭", true),
    )

    val DEFAULTS: Set<String> = ALL.filter { it.default }.map { it.key }.toSet()

    /** 指令 / 步骤需要哪个功能。 */
    fun forCommand(type: String, args: org.json.JSONObject): String? = when (type) {
        "send_text" -> "reply"
        "reply_quote" -> "quote"
        "quick_reply" -> "quick_reply"
        "share_file" -> if (FileShareProvider.mimeOf(args.optString("filename")).startsWith("image/")) "images" else "files"
        "snapshot", "dump" -> "read"
        else -> null
    }

    fun forStep(step: String): String? = when (step) {
        "read", "wait_for" -> "read"
        "screenshot" -> "screenshot"
        "launch", "tap", "input", "scroll", "back", "home", "long_press", "swipe", "notify_action" -> "control"
        else -> null
    }

    fun require(cfg: Config, key: String?) {
        if (key != null && key !in cfg.features) {
            val label = ALL.firstOrNull { it.key == key }?.label ?: key
            throw CmdError("feature_disabled", "手机上关闭了「$label」功能（设置页可以打开）")
        }
    }
}
