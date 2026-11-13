package io.github.tonieeie.wecomdroid

import android.accessibilityservice.AccessibilityService
import android.app.ActivityOptions
import android.app.PendingIntent
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

class CmdError(val code: String, message: String) : Exception(message)

/**
 * 比对消息用的规范化：企业微信在 @名字 后面插不换行空格，换行和多个空格也不稳定，
 * 下面列出的空白字符连续多个折成一个普通空格，去掉首尾。
 *
 * 必须和服务器 rules.py 的 NORM_WS / norm() 一字不差。不能用 Kotlin 的 \s：
 * 它不认全角空格 　，而 Python 认，两边结果会对不上。
 */
const val NORM_WS = " \t\n\r\u000C\u000B 　    "
// 每个字符写成 \uXXXX 放进字符类，避免任何字符在正则里被当成特殊符号
private val NORM_RE = Regex("[" + NORM_WS.map { "\\u%04x".format(it.code) }.joinToString("") + "]+")

fun norm(s: String): String = NORM_RE.replace(s, " ").trim(' ')

/**
 * 手机上唯一会"动"企业微信的地方。只做三个原子动作，全都尽量不依赖控件 ID
 * （企业微信的资源 ID 是混淆过的，每个版本都可能变）：
 *
 *  - [openChat]：触发通知自带的点击意图打开会话，再核对标题栏确实是这个会话
 *  - [readScreen]：把当前界面所有文字按顺序读出来
 *  - [sendText]：找"唯一的可编辑输入框" → 填字 → 点文字为"发送"的按钮 → 确认输入框被清空
 *
 * 认不出来时一律报错停手，绝不猜着点 —— 发错群比不发严重得多。
 */
class BotAccessibilityService : AccessibilityService() {

    private val main = Handler(Looper.getMainLooper())
    private lateinit var cfg: Config
    private var lastAutoDumpAt = 0L

    override fun onServiceConnected() {
        cfg = Config(this)
        instance = this
        Status.accessibilityConnected = true
        Uploader.start(this)
    }

    override fun onDestroy() {
        markDisconnected()
        super.onDestroy()
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        markDisconnected()
        return super.onUnbind(intent)
    }

    private fun markDisconnected() {
        if (instance === this) instance = null
        Status.accessibilityConnected = false
        Status.error("无障碍服务被关闭")
    }

    override fun onInterrupt() = Unit

    override fun onAccessibilityEvent(e: AccessibilityEvent) {
        if (e.packageName?.toString() !in cfg.apps) return
        Status.lastWeComEventAt = System.currentTimeMillis()

        // 侦察模式：每换一个界面，等内容加载完再导出整棵树。执行指令期间不导，免得刷屏。
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            cfg.dumpMode && !CommandRunner.busy
        ) {
            val now = System.currentTimeMillis()
            if (now - lastAutoDumpAt < 2_000) return
            lastAutoDumpAt = now
            val activity = e.className?.toString()
            main.postDelayed({ enqueueDump("auto", activity) }, 1_000)
        }
    }

    fun enqueueDump(reason: String, activity: String? = null) {
        val root = appRoot() ?: return
        val payload = JSONObject().apply {
            put("reason", reason)
            put("package", root.packageName?.toString())
            put("activity", activity)
            put("screen", screenSize())
            put("tree", TreeDumper.tree(root))
        }
        EventQueue.get(this).enqueue("ui_dump", payload, cfg.deviceId)
    }

    // ---------- 以下供 CommandRunner 在后台线程调用 ----------

    fun openChat(chat: String) {
        val entry = ChatRegistry.get(chat)
            ?: throw CmdError("no_route", "最近没有收到「$chat」的通知，打不开这个会话（App 重启后要等对方再发一条）")

        val opts: Bundle? = if (Build.VERSION.SDK_INT >= 34) {
            ActivityOptions.makeBasic()
                .setPendingIntentBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED
                ).toBundle()
        } else null

        try {
            entry.intent.send(this, 0, null, null, null, null, opts)
        } catch (e: PendingIntent.CanceledException) {
            throw CmdError("intent_canceled", "「$chat」的通知已失效，等对方再发一条")
        }

        waitFor(8_000) {
            val root = appRoot() ?: return@waitFor null
            if (titleMatches(root, chat) && findEditable(root) != null) true else null
        } ?: throw CmdError(
            "chat_not_opened",
            "打开后没认出「$chat」的聊天界面（标题不符或没有输入框），已停止，不发送"
        )
    }

    fun readScreen(): JSONObject {
        val root = appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用（见设置页的应用列表）")
        return JSONObject().apply {
            put("screen", screenSize())
            put("nodes", TreeDumper.flat(root))
        }
    }

    fun dumpTree(): JSONObject {
        val root = appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用（见设置页的应用列表）")
        return JSONObject().apply {
            put("screen", screenSize())
            put("tree", TreeDumper.tree(root))
        }
    }

    fun sendText(text: String, sendLabel: String = "发送") {
        val root = appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用（见设置页的应用列表）")
        val input = findEditable(root)
            ?: throw CmdError("no_input", "没找到输入框（可能处于语音输入模式）")

        input.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        if (!input.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            throw CmdError("set_text_failed", "往输入框填字失败")
        }

        // 填字后"发送"按钮才会出现（空输入框时那个位置是"+"）。
        val sendBtn = waitFor(3_000) { appRoot()?.let { findByExactText(it, sendLabel) } }
            ?: throw CmdError("no_send_button", "填字后没出现「$sendLabel」按钮")
        if (!click(sendBtn)) throw CmdError("click_failed", "点「$sendLabel」失败")

        // 发出去的判据：输入框被清空。没清空就如实报"不确定"，交给人看，不重试（防重复发送）。
        waitFor(3_000) {
            val r = appRoot() ?: return@waitFor null
            val e = findEditable(r) ?: return@waitFor null
            val now = e.text?.toString().orEmpty()
            if (now != text) true else null
        } ?: throw CmdError("send_unconfirmed", "点了发送但输入框没清空，不确定是否发出 —— 请人工看一眼")
    }

    fun goHome() {
        performGlobalAction(GLOBAL_ACTION_HOME)
    }

    /**
     * 在当前会话里找到原消息并点"引用"，让接下来 [sendText] 发出的内容挂在它下面。
     *
     * [key] 是原消息文字的规范化形式（见 [norm]），由服务器从当初的会话快照里取出 ——
     * 跟屏幕上读到的是同一个来源，所以用"完全相等"比对，不靠前缀猜。
     * 当前屏幕没有就往上翻，最多翻 [maxPages] 页。同样的文字出现多次时取最下面（最新）那条。
     *
     * 返回 null 表示已点上"引用"；否则返回没做成的原因（界面已恢复，可以直接普通发送）。
     * 长按菜单里只点文字恰好是"引用"的那一项 —— 旁边就是"撤回""删除"，点错不可挽回。
     */
    fun quoteMessage(key: String, maxPages: Int, quoteLabel: String = "引用"): String? {
        var bubble = findBubble(key)
        var pages = 0
        while (bubble == null && pages < maxPages) {
            if (!scrollMessagesUp()) break
            Thread.sleep(700)
            bubble = findBubble(key)
            pages++
        }
        if (bubble == null) return "not_found"

        if (!longClick(bubble)) return "long_click_failed"
        val item = waitFor(2_000) { findInAllWindows { it.text?.toString()?.trim() == quoteLabel } }
        if (item == null) {
            performGlobalAction(GLOBAL_ACTION_BACK) // 关掉长按菜单
            Thread.sleep(400)
            return "no_quote_menu"
        }
        if (!click(item)) {
            performGlobalAction(GLOBAL_ACTION_BACK)
            Thread.sleep(400)
            return "click_quote_failed"
        }
        Thread.sleep(500)
        return null
    }

    /**
     * 把文件分享到企业微信的某个会话 —— 跟人在文件管理器里点"分享 → 企业微信 → 选群 → 发送"一样。
     *
     * 不依赖通知入口（[ChatRegistry]）：文件往往隔很久才要发（比如几天后才出来的合同、发票），，
     * 那时手机多半重启过、入口早没了。企业微信自己的"选择聊天"界面不管多久以后都能用。
     *
     * 选群的规矩：名字**完全一致**（允许带人数后缀"群名(8)"）的恰好一个才点；
     * 一个都没有、或有重名的，一律停手。确认弹窗里再核对一次群名才点"发送"。
     * [caption] 填进确认弹窗的留言框（有的话），跟文件一起发出。
     */
    fun shareFile(file: java.io.File, chat: String, caption: String?,
                  pkg: String = WEWORK_PACKAGE, sendLabel: String = "发送"): JSONObject {
        if (pkg !in cfg.apps) throw CmdError("not_allowed_app", "$pkg 不在受控应用列表里")
        val detail = JSONObject()
        val uri = FileShareProvider.uriFor(file)
        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = FileShareProvider.mimeOf(file.name)
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            clipData = android.content.ClipData.newRawUri(file.name, uri)
            setPackage(pkg)
            addFlags(
                android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    android.content.Intent.FLAG_ACTIVITY_NEW_TASK or
                    android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK
            )
        }

        // 企业微信可能注册了好几个"分享"入口（发给同事 / 存微盘 / 发到邮件…）。只指定包名时，
        // 系统会先弹一个让人选的菜单 —— 那个菜单不属于企业微信，机器人就卡住了。
        // 所以把入口全列出来，挑"发给聊天"的那个，直接指名启动。
        val targets = packageManager.queryIntentActivities(intent, 0)
        detail.put("share_targets", org.json.JSONArray(targets.map {
            "${it.loadLabel(packageManager)} | ${it.activityInfo.name}"
        }))
        val chosen = pickChatShareTarget(targets)
            ?: throw CmdError("no_share_target", "企业微信没有可接收文件分享的入口：${detail.optJSONArray("share_targets")}")
        detail.put("share_target", chosen.activityInfo.name)
        intent.setClassName(chosen.activityInfo.packageName, chosen.activityInfo.name)

        try {
            startActivity(intent)
        } catch (e: Exception) {
            throw CmdError("share_start_failed", "拉起企业微信分享失败：${e.message}")
        }

        // 1. 等"选择聊天"界面出来：能看到这个群名，或者至少有搜索入口
        waitFor(8_000) {
            appRoot()?.let { r ->
                if (chatMatches(r, chat).isNotEmpty() || findSearchEntry(r) != null) true else null
            }
        } ?: throw CmdError(
            "picker_not_shown",
            "没等到企业微信的「选择聊天」界面。用的入口=${chosen.activityInfo.name}；" +
                "全部入口=${detail.optJSONArray("share_targets")}；当前屏幕：${describeForeground()}"
        )

        // 2. 先在最近聊天里找；没有再搜
        var hits = appRoot()?.let { chatMatches(it, chat) } ?: emptyList()
        detail.put("found_in", "recent")
        if (hits.isEmpty()) {
            detail.put("found_in", "search")
            hits = searchChat(chat)
        }
        if (hits.isEmpty()) throw CmdError("chat_not_found", "「选择聊天」里找不到名为「$chat」的会话，未发送")
        if (hits.size > 1) throw CmdError("chat_ambiguous", "有 ${hits.size} 个会话都叫「$chat」，分不清，未发送")
        val picked = Rect().also { hits[0].getBoundsInScreen(it) }
        if (!click(hits[0])) throw CmdError("click_failed", "点选「$chat」失败")

        // 3. 确认弹窗：核对群名，填留言，点发送
        val sendBtn = waitFor(5_000) { findInAllWindows { it.text?.toString()?.trim() == sendLabel } }
            ?: throw CmdError("no_confirm_dialog", "点选后没出现「发送」确认")
        // 只在弹窗自己那个窗口里核对；背后的会话列表里也有这个群名，搜全部窗口会被它蒙混过关。
        // 万一弹窗跟列表在同一个窗口，就排除掉刚才点的那一条（按屏幕位置）。
        val dialogRoot = sendBtn.window?.root ?: appRoot()
        val dialogShowsChat = dialogRoot != null && chatMatches(dialogRoot, chat).any { n ->
            Rect().also { n.getBoundsInScreen(it) } != picked
        }
        if (!dialogShowsChat) {
            performGlobalAction(GLOBAL_ACTION_BACK)
            throw CmdError("confirm_mismatch", "确认弹窗里没看到「$chat」，已取消，未发送")
        }

        if (!caption.isNullOrBlank()) {
            // 留言框只在弹窗里找，别填进背后列表的搜索框
            var box: AccessibilityNodeInfo? = null
            TreeDumper.walk(dialogRoot!!) { n -> if (box == null && n.isEditable && n.isVisibleToUser) box = n }
            val ok = box?.performAction(
                AccessibilityNodeInfo.ACTION_SET_TEXT,
                Bundle().apply {
                    putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, caption)
                }
            ) == true
            detail.put("caption_attached", ok)
        }
        if (!click(sendBtn)) throw CmdError("click_failed", "点「发送」失败")

        // 4. 弹窗消失 = 已提交给企业微信发送
        waitFor(5_000) {
            if (findInAllWindows { it.text?.toString()?.trim() == sendLabel && it.isClickable } == null) true else null
        } ?: throw CmdError("send_unconfirmed", "点了发送但确认弹窗没关，不确定是否发出 —— 请人工看一眼")
        return detail
    }

    /**
     * 在企业微信的分享入口里挑"发给聊天"的那个。按名称关键词打分，拿不准就选第一个
     * （失败时 detail.share_targets 会把全部入口报给服务器，下一版据此修正）。
     */
    private fun pickChatShareTarget(
        targets: List<android.content.pm.ResolveInfo>,
    ): android.content.pm.ResolveInfo? {
        if (targets.isEmpty()) return null
        fun score(r: android.content.pm.ResolveInfo): Int {
            val label = r.loadLabel(packageManager).toString()
            val name = r.activityInfo.name
            var s = 0
            if (label == "企业微信" || label.contains("同事") || label.contains("聊天")) s += 10
            if (name.contains("Share", ignoreCase = true) || name.contains("Forward", ignoreCase = true)) s += 3
            if (listOf("微盘", "收藏", "邮件", "日程", "文档", "打印", "笔记").any { label.contains(it) }) s -= 20
            return s
        }
        return targets.maxByOrNull(::score)
    }

    /** 不管前台是哪个 App，说出它是谁、屏幕上有哪些字 —— 卡住时报给服务器排查用。 */
    fun describeForeground(): String {
        val root = rootInActiveWindow ?: return "（读不到前台窗口）"
        val texts = mutableListOf<String>()
        TreeDumper.walk(root) { n ->
            val t = (n.text ?: n.contentDescription)?.toString()?.trim()
            if (!t.isNullOrEmpty() && texts.size < 40) texts.add(t)
        }
        return "${root.packageName}：" + texts.joinToString(" | ")
    }

    /** 屏幕上名字跟 [chat] 完全一致的会话条目（排除输入框）。 */
    private fun chatMatches(root: AccessibilityNodeInfo, chat: String): List<AccessibilityNodeInfo> {
        val out = mutableListOf<AccessibilityNodeInfo>()
        TreeDumper.walk(root) { n ->
            if (n.isEditable || !n.isVisibleToUser) return@walk
            val t = n.text?.toString()?.trim() ?: return@walk
            if (t == chat || Regex("^" + Regex.escape(chat) + "[(（]\\d+[)）]$").matches(t)) out.add(n)
        }
        return out
    }

    private fun findSearchEntry(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var hit: AccessibilityNodeInfo? = null
        TreeDumper.walk(root) { n ->
            if (hit != null || !n.isVisibleToUser) return@walk
            val label = (n.text ?: n.contentDescription)?.toString()?.trim() ?: return@walk
            if (n.isEditable || label == "搜索" || label.startsWith("搜索")) hit = n
        }
        return hit
    }

    private fun searchChat(chat: String): List<AccessibilityNodeInfo> {
        val root = appRoot() ?: return emptyList()
        val entry = findSearchEntry(root) ?: throw CmdError("no_search", "「选择聊天」里没找到搜索框")
        if (!entry.isEditable) {
            click(entry)
            Thread.sleep(600)
        }
        val box = waitFor(3_000) { appRoot()?.let { findEditable(it) } }
            ?: throw CmdError("no_search", "点了搜索但没出现输入框")
        box.performAction(
            AccessibilityNodeInfo.ACTION_SET_TEXT,
            Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, chat) }
        )
        // 搜索结果是异步出来的；等它稳定一下再数
        var last = -1
        var stable = 0
        for (i in 0 until 15) {
            Thread.sleep(300)
            val n = appRoot()?.let { chatMatches(it, chat).size } ?: 0
            if (n == last && n > 0) stable++ else stable = 0
            last = n
            if (stable >= 2) break
        }
        return appRoot()?.let { chatMatches(it, chat) } ?: emptyList()
    }

    private fun findBubble(key: String): AccessibilityNodeInfo? {
        val root = appRoot() ?: return null
        var best: AccessibilityNodeInfo? = null
        var bestTop = Int.MIN_VALUE
        val r = Rect()
        TreeDumper.walk(root) { n ->
            val t = n.text?.toString() ?: return@walk
            if (n.isEditable || !n.isVisibleToUser || norm(t) != key) return@walk
            n.getBoundsInScreen(r)
            if (r.top > bestTop) { best = n; bestTop = r.top }
        }
        return best
    }

    /** 消息列表 = 面积最大的可滚动控件。往上翻一页（看更早的消息）。 */
    private fun scrollMessagesUp(): Boolean {
        val root = appRoot() ?: return false
        var list: AccessibilityNodeInfo? = null
        var area = 0
        val r = Rect()
        TreeDumper.walk(root) { n ->
            if (!n.isScrollable) return@walk
            n.getBoundsInScreen(r)
            val a = r.width() * r.height()
            if (a > area) { list = n; area = a }
        }
        return list?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD) == true
    }

    private fun longClick(node: AccessibilityNodeInfo): Boolean {
        var n: AccessibilityNodeInfo? = node
        var hops = 0
        while (n != null && hops < 5) {
            if (n.isLongClickable) return n.performAction(AccessibilityNodeInfo.ACTION_LONG_CLICK)
            n = n.parent
            hops++
        }
        return false
    }

    /** 长按菜单常是单独的弹出窗口，不在 rootInActiveWindow 里，要遍历所有窗口找。 */
    private fun findInAllWindows(pred: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        val roots = windows.mapNotNull { it.root }.ifEmpty { listOfNotNull(rootInActiveWindow) }
        for (root in roots) {
            if (root.packageName?.toString() !in cfg.apps) continue
            var hit: AccessibilityNodeInfo? = null
            TreeDumper.walk(root) { n -> if (hit == null && n.isVisibleToUser && pred(n)) hit = n }
            if (hit != null) return hit
        }
        return null
    }

    // ---------- 通用动作：对任何受控应用都能用 ----------

    /** 打开一个受控应用，等它到前台。 */
    fun launch(pkg: String) {
        if (pkg !in cfg.apps) throw CmdError("not_allowed_app", "$pkg 不在受控应用列表里")
        val intent = packageManager.getLaunchIntentForPackage(pkg)
            ?: throw CmdError("not_installed", "手机上没装 $pkg，或它没有可启动的界面")
        intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            startActivity(intent)
        } catch (e: Exception) {
            throw CmdError("launch_failed", "打开 $pkg 失败：${e.message}")
        }
        waitFor(8_000) { if (rootInActiveWindow?.packageName?.toString() == pkg) true else null }
            ?: throw CmdError("launch_timeout", "$pkg 没有到前台。当前屏幕：${describeForeground()}")
    }

    /** 点一个控件：按文字 / 无障碍描述找（默认完全相等，contains=true 时包含即可）。只在受控应用里找。 */
    fun tapText(label: String, contains: Boolean) {
        val node = waitFor(3_000) {
            findInAllWindows { n ->
                val t = (n.text ?: n.contentDescription)?.toString()?.trim() ?: return@findInAllWindows false
                if (contains) t.contains(label) else t == label
            }
        } ?: throw CmdError("not_found", "屏幕上没找到「$label」")
        if (!click(node)) throw CmdError("click_failed", "点「$label」失败")
    }

    /** 点屏幕坐标。前台必须是受控应用。 */
    fun tapAt(x: Int, y: Int) {
        appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用")
        val path = android.graphics.Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = android.accessibilityservice.GestureDescription.Builder()
            .addStroke(android.accessibilityservice.GestureDescription.StrokeDescription(path, 0, 60)).build()
        if (!dispatchGesture(gesture, null, null)) throw CmdError("click_failed", "点击 ($x,$y) 失败")
        Thread.sleep(150)
    }

    /** 往输入框里填字：屏幕上唯一的输入框，或当前有焦点的那个。 */
    fun inputText(text: String) {
        val root = appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用")
        val box = findEditable(root) ?: root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable }
            ?: throw CmdError("no_input", "没找到输入框（屏幕上没有，或有多个且都没焦点）")
        val ok = box.performAction(
            AccessibilityNodeInfo.ACTION_SET_TEXT,
            Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        )
        if (!ok) throw CmdError("set_text_failed", "往输入框填字失败")
    }

    /** 滚动最大的可滚动区域。down = 看后面的内容。 */
    fun scroll(down: Boolean) {
        val root = appRoot() ?: throw CmdError("not_target_app", "当前前台不是受控应用")
        var list: AccessibilityNodeInfo? = null
        var area = 0
        val r = Rect()
        TreeDumper.walk(root) { n ->
            if (!n.isScrollable) return@walk
            n.getBoundsInScreen(r)
            if (r.width() * r.height() > area) { list = n; area = r.width() * r.height() }
        }
        val action = if (down) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        if (list?.performAction(action) != true) throw CmdError("scroll_failed", "没有可滚动的区域，或已经到头")
    }

    fun back() {
        performGlobalAction(GLOBAL_ACTION_BACK)
    }

    /** 当前前台应用的包名（给结果里带上，方便服务器确认读的是谁）。 */
    fun foregroundPackage(): String? = rootInActiveWindow?.packageName?.toString()

    // ---------- 界面识别小工具 ----------

    /** 前台窗口，前提是它属于受控应用；否则 null —— 没列出的应用一律不读不点。 */
    private fun appRoot(): AccessibilityNodeInfo? =
        rootInActiveWindow?.takeIf { it.packageName?.toString() in cfg.apps }

    private fun screenSize(): String {
        val m = resources.displayMetrics
        return "${m.widthPixels}x${m.heightPixels}"
    }

    /** 标题栏（屏幕顶部 15% 内）有一行字是会话名，允许带成员数后缀 "群名(8)"。 */
    private fun titleMatches(root: AccessibilityNodeInfo, chat: String): Boolean {
        val limit = resources.displayMetrics.heightPixels * 0.15
        var hit = false
        val r = Rect()
        TreeDumper.walk(root) { n ->
            if (hit) return@walk
            val t = n.text?.toString()?.trim() ?: return@walk
            n.getBoundsInScreen(r)
            if (r.top < limit && (t == chat || t.startsWith("$chat(") || t.startsWith("$chat（"))) hit = true
        }
        return hit
    }

    /** 屏幕上恰好一个可见的可编辑框才算数；多于一个说明不在普通聊天界面。 */
    private fun findEditable(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val found = mutableListOf<AccessibilityNodeInfo>()
        TreeDumper.walk(root) { n -> if (n.isEditable && n.isVisibleToUser) found.add(n) }
        return found.singleOrNull()
    }

    private fun findByExactText(root: AccessibilityNodeInfo, text: String): AccessibilityNodeInfo? {
        var hit: AccessibilityNodeInfo? = null
        TreeDumper.walk(root) { n ->
            if (hit == null && n.isVisibleToUser && n.text?.toString()?.trim() == text) hit = n
        }
        return hit
    }

    /**
     * 文字节点本身常常不可点，往上找第一个可点的父节点。
     * 有的列表（如企业微信分享时的"最近聊天"）整行都不标"可点"，是靠触摸事件响应的 ——
     * 那就在文字的屏幕位置模拟一次手指点击。
     */
    private fun click(node: AccessibilityNodeInfo): Boolean {
        var n: AccessibilityNodeInfo? = node
        var hops = 0
        while (n != null && hops < 8) {
            if (n.isClickable && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
            n = n.parent
            hops++
        }
        return tapCenter(node)
    }

    private fun tapCenter(node: AccessibilityNodeInfo): Boolean {
        val r = Rect()
        node.getBoundsInScreen(r)
        val m = resources.displayMetrics
        if (r.isEmpty || r.centerX() !in 0 until m.widthPixels || r.centerY() !in 0 until m.heightPixels) {
            return false
        }
        val path = android.graphics.Path().apply { moveTo(r.exactCenterX(), r.exactCenterY()) }
        val gesture = android.accessibilityservice.GestureDescription.Builder()
            .addStroke(android.accessibilityservice.GestureDescription.StrokeDescription(path, 0, 60))
            .build()
        val done = java.util.concurrent.CountDownLatch(1)
        var ok = false
        val dispatched = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(g: android.accessibilityservice.GestureDescription?) {
                ok = true; done.countDown()
            }
            override fun onCancelled(g: android.accessibilityservice.GestureDescription?) {
                done.countDown()
            }
        }, null)
        if (!dispatched) return false
        done.await(2, java.util.concurrent.TimeUnit.SECONDS)
        return ok
    }

    private fun <T> waitFor(timeoutMs: Long, probe: () -> T?): T? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            try {
                probe()?.let { return it }
            } catch (_: Exception) {
                // 界面切换瞬间节点可能失效，下一轮再取
            }
            Thread.sleep(200)
        }
        return null
    }

    companion object {
        @Volatile var instance: BotAccessibilityService? = null
    }
}
