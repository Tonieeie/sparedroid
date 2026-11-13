plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.tonieeie.sparedroid"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.tonieeie.sparedroid"
        minSdk = 26
        targetSdk = 34
        versionCode = 5
        versionName = "0.3.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // 自用侧载，不上架：release 也用 debug 签名，省掉管理签名文件。
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// 刻意零第三方依赖：只用 Android 框架自带的 org.json / HttpURLConnection / SQLite。
// 依赖越少，这台常年无人值守的手机上出怪问题的面越小。
