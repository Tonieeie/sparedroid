package io.github.tonieeie.sparedroid

import android.app.PendingIntent

/**
 * 会话名 → 打开这个会话的"门票"（企业微信通知自带的 PendingIntent）。
 *
 * 为什么不靠在企业微信里点搜索框找群：搜索界面每个版本都可能变，而通知的点击意图
 * 是企业微信自己生成的，触发它就会直接打开那个会话，跟界面布局无关。
 * 代价是只能回复"最近给我们发过通知"的会话 —— 这正好就是 "谁 @ 了机器人就回谁" 的场景。
 *
 * 只存在内存里：PendingIntent 不能落盘，进程重启后要等对方再发一条才能回。
 */
object ChatRegistry {
    data class Entry(
        val intent: PendingIntent,
        val seenAt: Long,
        /** 通知上带输入框的「回复」按钮（有的话）—— 快捷回复用。 */
        val reply: android.app.Notification.Action? = null,
        /** 通知上的全部按钮（标为已读、回复、接听……），按文字点。 */
        val actions: List<android.app.Notification.Action> = emptyList(),
    )

    private const val MAX = 300
    private val map = object : LinkedHashMap<String, Entry>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Entry>?) = size > MAX
    }

    fun put(chat: String, intent: PendingIntent, actions: List<android.app.Notification.Action> = emptyList()) =
        synchronized(map) {
            val reply = actions.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }
            map[chat] = Entry(intent, System.currentTimeMillis(), reply, actions)
        }

    fun get(chat: String): Entry? = synchronized(map) { map[chat] }

    fun names(): List<String> = synchronized(map) { map.keys.toList() }
}
