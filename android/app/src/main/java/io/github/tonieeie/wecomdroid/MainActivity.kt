package io.github.tonieeie.wecomdroid

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 设置页 + 状态面板。布局用代码拼，省掉 XML 和 AndroidX 依赖。
 * 上面填配置、点几个"去开权限"的按钮；下面每 2 秒刷新一次运行状态。
 */
class MainActivity : Activity() {
    private lateinit var cfg: Config
    private lateinit var statusView: TextView
    private val handler = Handler(Looper.getMainLooper())
    private val refresher = object : Runnable {
        override fun run() {
            refreshStatus()
            handler.postDelayed(this, 2_000)
        }
    }

    @SuppressLint("UseSwitchCompatOrMaterialCode", "SetTextI18n")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        cfg = Config(this)
        Uploader.start(this)

        val pad = (16 * resources.displayMetrics.density).toInt()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }

        fun label(t: String) = TextView(this).apply { text = t; setPadding(0, pad / 2, 0, 0) }
        fun field(v: String, hint: String, secret: Boolean = false) = EditText(this).apply {
            setText(v); this.hint = hint; isSingleLine = true
            inputType = if (secret) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        fun button(t: String, onClick: () -> Unit) = Button(this).apply {
            text = t; setOnClickListener { onClick() }
        }

        val endpoint = field(cfg.endpoint, "https://bot.example.com")
        val token = field(cfg.token, "和服务器约定的口令", secret = true)
        val botName = field(cfg.botName, "机器人在群里的名字（可留空）")
        val dump = Switch(this).apply {
            text = "侦察模式（每换一个界面就上传控件树）"
            isChecked = cfg.dumpMode
            setOnCheckedChangeListener { _, on -> cfg.dumpMode = on }
        }

        val apps = field(cfg.apps.joinToString(","), "受控应用包名，逗号分隔")
        val pin = field(cfg.certPin, "服务器证书指纹（连 VPS 必填；局域网调试留空）")

        // 口令和指纹都是几十位的乱码，手敲必错。服务器上 `wecomdroid config`
        // 打印一行 JSON，复制到手机后点这个按钮，四项一次填好并保存。
        col.addView(button("从剪贴板导入配置") {
            val clip = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
            val text = clip.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString().orEmpty()
            try {
                val json = org.json.JSONObject(text.trim())
                val ep = json.getString("endpoint").trim()
                val tk = json.getString("token").trim()
                if (!ep.startsWith("http") || ep.contains('<') || tk.isEmpty()) error("bad")
                endpoint.setText(ep)
                token.setText(tk)
                pin.setText(json.optString("pin"))
                if (json.optString("bot").isNotEmpty()) botName.setText(json.optString("bot"))
                json.optJSONArray("apps")?.let { a ->
                    val list = (0 until a.length()).map { a.getString(it) }.toSet()
                    if (list.isNotEmpty()) { cfg.apps = list; apps.setText(list.joinToString(",")) }
                }
                cfg.endpoint = ep
                cfg.token = tk
                cfg.certPin = json.optString("pin")
                cfg.botName = botName.text.toString()
                Uploader.wake()
                toast("已导入并保存")
            } catch (e: Exception) {
                toast("剪贴板里不是有效的配置（服务器地址里的 <服务器公网IP> 换成真实地址了吗？）")
            }
        })
        col.addView(label("服务器地址"))
        col.addView(endpoint)
        col.addView(label("口令"))
        col.addView(token)
        col.addView(label("服务器证书指纹"))
        col.addView(pin)
        col.addView(label("机器人显示名"))
        col.addView(botName)
        col.addView(label("受控应用（只有这里列出的应用会被读取和操作）"))
        col.addView(apps)
        col.addView(button("保存") {
            cfg.endpoint = endpoint.text.toString()
            cfg.token = token.text.toString()
            cfg.certPin = pin.text.toString()
            cfg.botName = botName.text.toString()
            cfg.apps = apps.text.toString().split(',', ' ', '|').map { it.trim() }.filter { it.isNotEmpty() }.toSet()
            Uploader.wake()
            Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show()
        })
        col.addView(dump)

        col.addView(label("—— 第一次使用，依次打开下面三项 ——"))
        col.addView(button("① 打开通知使用权（找到「WeComDroid」并允许）") {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        })
        col.addView(button("② 打开无障碍（已安装的服务 → WeComDroid）") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        col.addView(button("③ 关闭省电限制（防止被系统杀掉）") { requestIgnoreBattery() })

        col.addView(label("—— 调试 ——"))
        col.addView(button("立即导出一次企业微信界面") {
            val svc = BotAccessibilityService.instance
            if (svc == null) toast("无障碍没开") else {
                toast("5 秒后导出，请切到企业微信要看的界面")
                handler.postDelayed({ svc.enqueueDump("manual") }, 5_000)
            }
        })

        statusView = TextView(this).apply { setTextIsSelectable(true); setPadding(0, pad, 0, 0) }
        col.addView(statusView)

        setContentView(ScrollView(this).apply { addView(col, MATCH_PARENT, WRAP_CONTENT) })
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresher)
    }

    override fun onPause() {
        handler.removeCallbacks(refresher)
        super.onPause()
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    @SuppressLint("BatteryLife")
    private fun requestIgnoreBattery() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("已经是不受限制状态"); return
        }
        startActivity(
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
        )
    }

    private fun listenerGranted(): Boolean {
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        val me = ComponentName(this, AppNotificationListener::class.java).flattenToString()
        return flat.split(":").any { it == me }
    }

    @SuppressLint("SetTextI18n")
    private fun refreshStatus() {
        val fmt = SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault())
        fun t(ms: Long) = if (ms == 0L) "从未" else fmt.format(Date(ms))
        fun ok(b: Boolean) = if (b) "✅" else "❌"
        val pm = getSystemService(POWER_SERVICE) as PowerManager

        statusView.text = """
            ${ok(cfg.isConfigured)} 服务器已配置
            ${ok(listenerGranted())} 通知使用权（连接中：${ok(Status.listenerConnected)}）
            ${ok(Status.accessibilityConnected)} 无障碍服务
            ${ok(pm.isIgnoringBatteryOptimizations(packageName))} 不受省电限制

            最近企业微信通知：${t(Status.lastNotificationAt)}
            最近企业微信界面事件：${t(Status.lastWeComEventAt)}
            最近上传成功：${t(Status.lastUploadOkAt)}
            最近心跳成功：${t(Status.lastHeartbeatOkAt)}
            待上传事件：${EventQueue.get(this).count()}
            最近指令：${Status.lastCommand.ifEmpty { "无" }}
            可回复的会话：${ChatRegistry.names().joinToString("、").ifEmpty { "无" }}

            最近错误（${t(Status.lastErrorAt)}）：
            ${Status.lastError.ifEmpty { "无" }}

            设备 ID：${cfg.deviceId}
            版本：${BuildConfigCompat.VERSION_NAME}
        """.trimIndent()
    }
}
