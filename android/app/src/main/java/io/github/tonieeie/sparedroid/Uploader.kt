package io.github.tonieeie.sparedroid

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.service.notification.NotificationListenerService
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

/**
 * 唯一和服务器说话的线程，循环做三件事：
 *   1. 把发件箱里的事件分批 POST 到 {endpoint}/events，服务器回 2xx 才删本地
 *   2. 每分钟 POST 一次 {endpoint}/heartbeat
 *   3. GET {endpoint}/commands 取服务器要手机做的事（发消息、抓会话），交给 [CommandRunner]
 *
 * 网络错误一律退避重试（2s → 最长 60s），从不放弃，也不丢数据。
 */
object Uploader {
    private const val BATCH = 50
    private const val HEARTBEAT_EVERY_MS = 60_000L
    private const val IDLE_POLL_MS = 3_000L
    private const val MAX_BACKOFF_MS = 60_000L

    private val lock = Object()
    @Volatile private var started = false
    private lateinit var appCtx: Context

    /** 最近处理过的指令 id。服务器可能在手机回报结果前重复下发同一条，不能发两遍。 */
    private val seenCommands = object : LinkedHashMap<String, Boolean>(64, 0.75f, false) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Boolean>?) = size > 500
    }

    fun start(ctx: Context) {
        synchronized(lock) {
            if (started) return
            started = true
            appCtx = ctx.applicationContext
        }
        Thread(::loop, "uploader").apply { isDaemon = true }.start()
    }

    /** 新事件入队时叫醒，不用等满一个轮询周期。 */
    fun wake() = synchronized(lock) { lock.notifyAll() }

    private fun loop() {
        val cfg = Config(appCtx)
        val queue = EventQueue.get(appCtx)
        var backoff = 0L
        var lastHeartbeat = 0L

        while (true) {
            try {
                if (!cfg.isConfigured) {
                    sleep(5_000); continue
                }
                val base = cfg.endpoint
                val token = cfg.token

                val now = System.currentTimeMillis()
                if (now - lastHeartbeat >= HEARTBEAT_EVERY_MS) {
                    sendHeartbeat(base, token, cfg, queue)
                    lastHeartbeat = now
                }

                var drained = false
                while (true) {
                    val batch = queue.peek(BATCH)
                    if (batch.isEmpty()) break
                    val body = JSONObject().put("events", JSONArray(batch.map { it.second }))
                    val r = Http.postJson("$base/events", token, body.toString())
                    if (!r.ok) throw RuntimeException("上传事件失败 HTTP ${r.code}: ${r.body.take(200)}")
                    queue.delete(batch.map { it.first })
                    Status.lastUploadOkAt = System.currentTimeMillis()
                    drained = true
                }

                pollCommands(base, token, cfg)

                backoff = 0L
                if (!drained) sleep(IDLE_POLL_MS)
            } catch (e: Exception) {
                Status.error("${e.javaClass.simpleName}: ${e.message}")
                backoff = if (backoff == 0L) 2_000L else (backoff * 2).coerceAtMost(MAX_BACKOFF_MS)
                sleep(backoff)
            }
        }
    }

    /**
     * 已授权通知使用权、系统却没绑定监听服务 —— 不少手机装完 App 或被杀后会这样，
     * 表现是"权限是开的，但一条通知都收不到"，而且不报任何错。每次心跳前检查一次，
     * 发现没连上就请系统重新绑定。
     */
    private fun ensureListenerBound() {
        if (Status.listenerConnected) return
        val cn = ComponentName(appCtx, AppNotificationListener::class.java)
        val enabled = Settings.Secure.getString(appCtx.contentResolver, "enabled_notification_listeners")
            ?.split(":")?.any { it == cn.flattenToString() } == true
        if (!enabled) return
        runCatching { NotificationListenerService.requestRebind(cn) }
            .onFailure { Status.error("请求重新绑定通知监听失败：${it.message}") }
    }

    private fun sendHeartbeat(base: String, token: String, cfg: Config, queue: EventQueue) {
        ensureListenerBound()
        val body = Status.toJson(queue.count()).apply {
            put("device_id", cfg.deviceId)
            put("sent_at", System.currentTimeMillis())
            put("dump_mode", cfg.dumpMode)
            // 屏幕和锁屏状态：动作失败时一眼看出是不是锁屏了
            val pm = appCtx.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
            val km = appCtx.getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager
            put("screen_on", pm.isInteractive)
            put("keyguard_locked", km.isKeyguardLocked)
        }
        val r = Http.postJson("$base/heartbeat", token, body.toString())
        if (!r.ok) throw RuntimeException("心跳失败 HTTP ${r.code}")
        Status.lastHeartbeatOkAt = System.currentTimeMillis()
    }

    private fun pollCommands(base: String, token: String, cfg: Config) {
        val dev = URLEncoder.encode(cfg.deviceId, "UTF-8")
        val r = Http.get("$base/commands?device_id=$dev", token)
        if (!r.ok) throw RuntimeException("取指令失败 HTTP ${r.code}")
        if (r.body.isBlank()) return
        val arr = JSONObject(r.body).optJSONArray("commands") ?: return
        for (i in 0 until arr.length()) {
            val cmd = arr.getJSONObject(i)
            val id = cmd.optString("id")
            if (id.isEmpty()) continue
            synchronized(seenCommands) {
                if (seenCommands.containsKey(id)) return@synchronized null
                seenCommands[id] = true
                id
            } ?: continue
            CommandRunner.submit(appCtx, cmd)
        }
    }

    private fun sleep(ms: Long) = synchronized(lock) { lock.wait(ms) }
}
