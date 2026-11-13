package io.github.tonieeie.sparedroid

import android.content.Context
import java.util.UUID

/** 默认受控应用：企业微信。其它应用在设置页 / 导入配置里加。 */
const val WEWORK_PACKAGE = "com.tencent.wework"

/** 手机上唯一需要人填的三样东西：服务器地址、口令、机器人在群里的显示名。 */
class Config(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("config", Context.MODE_PRIVATE)

    /** 例如 https://bot.example.com/wecom-bot ，不带结尾斜杠。 */
    var endpoint: String
        get() = sp.getString("endpoint", "")!!.trim().trimEnd('/')
        set(v) = sp.edit().putString("endpoint", v.trim()).apply()

    var token: String
        get() = sp.getString("token", "")!!.trim()
        set(v) = sp.edit().putString("token", v.trim()).apply()

    /** 机器人账号在群里的名字，用来在通知文本里认出 "@它"。可留空。 */
    var botName: String
        get() = sp.getString("bot_name", "")!!.trim()
        set(v) = sp.edit().putString("bot_name", v.trim()).apply()

    /** 服务器证书指纹，见 [Http.certPin]。连 VPS 时必填，局域网调试留空。 */
    var certPin: String
        get() = sp.getString("cert_pin", "")!!.trim()
        set(v) {
            sp.edit().putString("cert_pin", v.trim()).apply()
            Http.certPin = v.trim()
        }

    /**
     * 受控应用的包名。**只有这里列出的应用**，本 App 才会转发它的通知、读它的界面、替人点它。
     * 没列出的应用（比如银行、支付）一律不碰 —— 这是安全边界，不是功能开关。
     */
    var apps: Set<String>
        get() = sp.getString("apps", "")!!.split(',', ' ', '|', '\n')
            .map { it.trim() }.filter { it.isNotEmpty() }.toSet().ifEmpty { setOf(WEWORK_PACKAGE) }
        set(v) = sp.edit().putString("apps", v.joinToString(",")).apply()

    /** 侦察模式：企业微信每换一个界面就把整棵控件树传上去，用于摸清新版界面结构。 */
    var dumpMode: Boolean
        get() = sp.getBoolean("dump_mode", false)
        set(v) = sp.edit().putBoolean("dump_mode", v).apply()

    val deviceId: String
        get() {
            sp.getString("device_id", null)?.let { return it }
            val id = UUID.randomUUID().toString()
            sp.edit().putString("device_id", id).apply()
            return id
        }

    val isConfigured: Boolean get() = endpoint.isNotEmpty() && token.isNotEmpty()
}
