package io.github.tonieeie.sparedroid

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Diagnostics.installCrashRecorder(this)
        Http.certPin = Config(this).certPin
        Uploader.start(this)
        KeepAliveService.ensureRunning(this)
        // 每次进程启动报一次"上次是怎么没的"：崩溃 / 被系统杀 / 手机重启
        runCatching {
            EventQueue.get(this).enqueue("app_start", Diagnostics.startupReport(this), Config(this).deviceId)
        }
    }
}
