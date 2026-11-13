package io.github.tonieeie.sparedroid

import android.app.Notification
import android.os.Bundle
import android.os.Parcelable
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject

/**
 * 发现新消息的入口：企业微信每来一条消息都会发系统通知，这里原样转给服务器。
 *
 * 通知是"事件驱动"的 —— 不用一直盯着屏幕，也不用在企业微信里来回切换界面。
 * 缺点是通知文字可能被截断（长消息只显示前几行），所以服务器看到 @ 了机器人后，
 * 会再下发一条 snapshot 指令，让无障碍服务打开会话读完整内容。
 *
 * 这里不判断"这条消息该怎么回"，只做一件事：把通知里能拿到的字段全部原样带上，
 * 由服务器解析。企业微信改通知格式时，只改服务器的 Python，不用重装 App。
 */
class AppNotificationListener : NotificationListenerService() {

    override fun onListenerConnected() {
        Status.listenerConnected = true
        Uploader.start(this)
    }

    override fun onListenerDisconnected() {
        Status.listenerConnected = false
        Status.error("通知监听被系统断开")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val n = sbn.notification ?: return
        // 分组摘要通知（"3 个会话的 10 条消息"）没有具体内容，跳过。
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val ex = n.extras ?: Bundle()
        val title = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString()
        val text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString()
        val bigText = ex.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
        val ticker = n.tickerText?.toString()

        val cfg = Config(this)
        if (sbn.packageName !in cfg.apps) return
        val haystack = listOfNotNull(title, text, bigText, ticker)
        val mentioned = haystack.any { s ->
            s.contains("[有人@我]") || s.contains("@我") ||
                (cfg.botName.isNotEmpty() && s.contains("@${cfg.botName}"))
        }

        val chat = ex.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString() ?: title
        if (chat != null && n.contentIntent != null) ChatRegistry.put(chat, n.contentIntent)

        val payload = JSONObject().apply {
            put("key", sbn.key)
            put("package", sbn.packageName)
            put("post_time", sbn.postTime)
            put("chat", chat)
            put("title", title)
            put("text", text)
            put("big_text", bigText)
            put("sub_text", ex.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString())
            put("ticker", ticker)
            put("is_group", ex.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false))
            put("mentioned", mentioned)
            put("can_reply", n.contentIntent != null)
            ex.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.let { lines ->
                put("text_lines", JSONArray(lines.map { it.toString() }))
            }
            messagingStyle(ex)?.let { put("messages", it) }
        }

        Status.lastNotificationAt = System.currentTimeMillis()
        EventQueue.get(this).enqueue("notification", payload, cfg.deviceId)
    }

    /** MessagingStyle 通知里逐条的 发送人/文本/时间（企业微信不一定用，有就带上）。 */
    @Suppress("DEPRECATION")
    private fun messagingStyle(ex: Bundle): JSONArray? {
        val arr: Array<Parcelable> = ex.getParcelableArray(Notification.EXTRA_MESSAGES) ?: return null
        val out = JSONArray()
        for (p in arr) {
            val b = p as? Bundle ?: continue
            out.put(JSONObject().apply {
                put("text", b.getCharSequence("text")?.toString())
                put("time", b.getLong("time"))
                put("sender", b.getCharSequence("sender")?.toString())
            })
        }
        return if (out.length() == 0) null else out
    }
}
