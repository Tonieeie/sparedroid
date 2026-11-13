package io.github.tonieeie.sparedroid

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Http.certPin = Config(this).certPin
        Uploader.start(this)
    }
}
