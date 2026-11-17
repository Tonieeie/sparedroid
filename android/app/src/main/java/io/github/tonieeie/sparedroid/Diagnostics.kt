package io.github.tonieeie.sparedroid

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 查"无障碍为什么总被关掉"用的诊断（无人值守的手机最常见的故障）。
 *
 * 服务器那边能看到的现象是：心跳整个停掉（App 进程没了），再回来时无障碍是关的。
 * 但光看服务器分不清是哪一种：
 *   - App 自己崩溃了（有的手机会把崩溃过的无障碍服务直接关掉）
 *   - 被系统 / 手机管家杀掉了（有的手机杀进程时顺手关掉它的无障碍开关）
 *   - 手机没电关机后重启
 * 所以 App 每次启动都把"上一次是怎么结束的"报给服务器：
 *   - 崩溃：自己记下来的崩溃堆栈（[installCrashRecorder]）
 *   - Android 11+：系统记录的退出原因（getHistoricalProcessExitReasons）
 *   - 开机多久了：几分钟 = 手机刚重启过；很久 = 只是 App 进程死了
 */
object Diagnostics {
    private const val CRASH_FILE = "last_crash.txt"
    private const val PREFS = "diagnostics"

    /** 进程启动时调用。崩溃时先把堆栈写到文件，再交给系统原来的处理（照常崩溃）。 */
    fun installCrashRecorder(ctx: Context) {
        val file = File(ctx.filesDir, CRASH_FILE)
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching {
                val trace = android.util.Log.getStackTraceString(error).take(6000)
                file.writeText("${System.currentTimeMillis()}\nthread: ${thread.name}\n$trace")
            }
            previous?.uncaughtException(thread, error)
        }
    }

    /** 每次心跳成功时记一下"我还活着"，下次启动时据此知道上次大概是什么时候没的。 */
    fun markAlive(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong("last_alive_at", System.currentTimeMillis()).apply()
    }

    /** App 启动时报一次：上次怎么结束的、手机是不是刚重启。 */
    fun startupReport(ctx: Context): JSONObject {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return JSONObject().apply {
            put("uptime_ms", SystemClock.elapsedRealtime())
            put("boot_count", Settings.Global.getInt(ctx.contentResolver, Settings.Global.BOOT_COUNT, -1))
            put("last_alive_at", prefs.getLong("last_alive_at", 0L))
            put("device", deviceInfo())
            val crash = File(ctx.filesDir, CRASH_FILE)
            if (crash.exists()) {
                put("crash", crash.readText().take(6000))
                crash.delete()
            }
            exitReasons(ctx)?.let { put("exit_reasons", it) }
        }
    }

    /** 心跳里带上：系统设置里这两个开关是不是开着（和"有没有连上"是两回事）。 */
    fun switches(ctx: Context): JSONObject = JSONObject().apply {
        val a11y = ComponentName(ctx, BotAccessibilityService::class.java).flattenToString()
        val listener = ComponentName(ctx, AppNotificationListener::class.java).flattenToString()
        put("a11y_enabled", Settings.Secure.getString(
            ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        )?.split(":")?.any { it.equals(a11y, ignoreCase = true) } == true)
        put("listener_enabled", Settings.Secure.getString(
            ctx.contentResolver, "enabled_notification_listeners"
        )?.split(":")?.any { it.equals(listener, ignoreCase = true) } == true)
        put("uptime_ms", SystemClock.elapsedRealtime())
    }

    fun deviceInfo(): String =
        "${Build.MANUFACTURER} ${Build.MODEL} / Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})"

    private fun exitReasons(ctx: Context): JSONArray? {
        if (Build.VERSION.SDK_INT < 30) return null
        val am = ctx.getSystemService(ActivityManager::class.java) ?: return null
        val out = JSONArray()
        runCatching { am.getHistoricalProcessExitReasons(ctx.packageName, 0, 3) }.getOrNull()?.forEach { info ->
            out.put(JSONObject().apply {
                put("at", info.timestamp)
                put("reason", reasonName(info.reason))
                put("description", info.description ?: "")
                put("importance", info.importance)
                put("status", info.status)
            })
        }
        return out
    }

    private fun reasonName(r: Int): String = when (r) {
        ApplicationExitInfo.REASON_CRASH -> "crash"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "crash_native"
        ApplicationExitInfo.REASON_ANR -> "anr"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "low_memory"
        ApplicationExitInfo.REASON_SIGNALED -> "signaled"
        ApplicationExitInfo.REASON_EXIT_SELF -> "exit_self"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "user_requested"
        ApplicationExitInfo.REASON_USER_STOPPED -> "user_stopped"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "excessive_resource_usage"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "permission_change"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "dependency_died"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "initialization_failure"
        ApplicationExitInfo.REASON_OTHER -> "other"
        else -> "code_$r"
    }
}
