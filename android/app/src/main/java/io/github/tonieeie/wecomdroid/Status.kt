package io.github.tonieeie.wecomdroid

import org.json.JSONObject

/**
 * 进程内的运行状态。设置页显示它，心跳把它原样报给服务器。
 *
 * 心跳的意义：手机最危险的故障不是崩溃，而是"服务看着还在、其实早就收不到消息了"
 * （无障碍被系统关掉、通知使用权被收回、企业微信被登出）。这些状态逐项上报，
 * 服务器那边才能在"很久没收到消息"时分辨是群里安静，还是手机已经瞎了。
 */
object Status {
    @Volatile var accessibilityConnected = false
    @Volatile var listenerConnected = false
    @Volatile var lastNotificationAt = 0L
    @Volatile var lastWeComEventAt = 0L
    @Volatile var lastUploadOkAt = 0L
    @Volatile var lastHeartbeatOkAt = 0L
    @Volatile var lastError: String = ""
    @Volatile var lastErrorAt = 0L
    @Volatile var lastCommand: String = ""

    fun error(msg: String) {
        lastError = msg
        lastErrorAt = System.currentTimeMillis()
    }

    fun toJson(queueSize: Int): JSONObject = JSONObject().apply {
        put("accessibility_connected", accessibilityConnected)
        put("listener_connected", listenerConnected)
        put("last_notification_at", lastNotificationAt)
        put("last_wecom_event_at", lastWeComEventAt)
        put("last_upload_ok_at", lastUploadOkAt)
        put("last_error", lastError)
        put("last_error_at", lastErrorAt)
        put("last_command", lastCommand)
        put("queue_size", queueSize)
        put("app_version", BuildConfigCompat.VERSION_NAME)
    }
}

/** 不开 buildConfig 生成，版本号手写一份，跟 app/build.gradle.kts 保持一致。 */
object BuildConfigCompat {
    const val VERSION_NAME = "0.2.0"
}
