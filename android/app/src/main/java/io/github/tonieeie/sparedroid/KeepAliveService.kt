package io.github.tonieeie.sparedroid

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

/**
 * 常驻前台服务：通知栏一直挂一条「SpareDroid 运行中」，并在熄屏时保持 CPU 和 WiFi 不睡。
 *
 * 真机上踩过：屏幕熄灭后，系统开始限制后台 App —— 心跳从每分钟一次拖到 3–4 分钟一次，
 * 然后 App 被杀了又拉起（无障碍和通知监听同时断开一分钟），最后彻底停了好几个小时。
 * 前台服务是安卓上"别把我当闲置后台杀掉"的标准做法；手机一直插着电，多出来的耗电不是问题。
 *
 * 不做成功能开关：它不是一种"能力"，关掉只会让手机在夜里悄悄掉线。
 *
 * 由 [ensureRunning] 在几个入口拉起：App 进程启动、打开设置页、无障碍服务连上、通知监听连上 ——
 * 进程被杀后系统会重新绑定无障碍服务，这里跟着就起来了。
 */
class KeepAliveService : Service() {

    private var cpuLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "后台运行", NotificationManager.IMPORTANCE_LOW).apply {
                description = "保持 SpareDroid 在后台运行，不会响铃或震动"
                setShowBadge(false)
            }
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("SpareDroid 运行中")
            .setContentText("保持在后台接收消息，请勿划掉")
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setOngoing(true)
            .setContentIntent(open)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        // CPU：熄屏后上传线程照常每分钟醒来发心跳、取指令
        cpuLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sparedroid:keepalive")
            .apply { setReferenceCounted(false); acquire() }
        // WiFi：不少手机熄屏后会让 WiFi 休眠甚至断开
        @Suppress("DEPRECATION")
        wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
            .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "sparedroid:keepalive")
            .apply { setReferenceCounted(false); acquire() }

        running = true
        Uploader.start(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        running = false
        cpuLock?.let { if (it.isHeld) it.release() }
        wifiLock?.let { if (it.isHeld) it.release() }
        Status.error("常驻服务被系统停止")
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "keepalive"
        private const val NOTIFICATION_ID = 1

        /** 心跳里报给服务器：常驻服务在不在跑。 */
        @Volatile var running = false
            private set

        /** 已经在跑就什么都不做。拉不起来（系统不让）记一条错误，随心跳报给服务器。 */
        fun ensureRunning(ctx: Context) {
            if (running) return
            try {
                ctx.startForegroundService(Intent(ctx, KeepAliveService::class.java))
            } catch (e: Exception) {
                Status.error("常驻服务启动失败：${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }
}
