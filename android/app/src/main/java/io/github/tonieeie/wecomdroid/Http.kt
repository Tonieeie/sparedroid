package io.github.tonieeie.wecomdroid

import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

data class HttpResult(val code: Int, val body: String) {
    val ok: Boolean get() = code in 200..299
}

object Http {
    private const val TIMEOUT_MS = 15_000

    /**
     * 服务器证书的 SHA-256 指纹（64 位十六进制）。填了就**只认这一张证书**。
     *
     * 服务器在 VPS 上只有一个公网 IP、没有域名，申请不了正规证书，用的是自签证书。
     * 自签证书系统默认不信任；与其关掉校验（等于明文），不如把这张证书的指纹钉死在手机里 ——
     * 别人就算劫持了网络，拿不出这张证书的私钥也冒充不了服务器。
     * 指纹已经唯一确定了对方身份，所以不再比对域名（用 IP 访问本来也没有域名可比）。
     *
     * 留空 = 走系统默认校验（正规证书的 https，或局域网调试用的 http）。
     */
    @Volatile var certPin: String = ""

    private fun open(url: String): HttpURLConnection {
        val conn = URL(url).openConnection() as HttpURLConnection
        val pin = certPin.lowercase().filter { it.isLetterOrDigit() }
        if (conn is HttpsURLConnection && pin.isNotEmpty()) {
            val tm = object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
                    throw CertificateException("not a server")

                override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                    val got = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded)
                        .joinToString("") { "%02x".format(it) }
                    if (!MessageDigest.isEqual(got.toByteArray(), pin.toByteArray())) {
                        throw CertificateException("服务器证书指纹不符（不是我们的服务器，或证书换过了）")
                    }
                }

                override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            }
            conn.sslSocketFactory = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }.socketFactory
            conn.hostnameVerifier = HostnameVerifier { _, _ -> true }
        }
        return conn
    }

    fun postJson(url: String, token: String, json: String): HttpResult =
        request("POST", url, token, json)

    fun get(url: String, token: String): HttpResult = request("GET", url, token, null)

    /** 下载到 [dest]：先写临时文件，完整收到才改名，半截文件永远不会被分享出去。 */
    fun download(url: String, token: String, dest: java.io.File, maxBytes: Long = 20L * 1024 * 1024) {
        val conn = open(url)
        val tmp = java.io.File(dest.parentFile, dest.name + ".part")
        try {
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = 60_000
            conn.setRequestProperty("Authorization", "Bearer $token")
            if (conn.responseCode !in 200..299) {
                throw CmdError("download_failed", "下载文件失败 HTTP ${conn.responseCode}")
            }
            var total = 0L
            conn.inputStream.use { input ->
                tmp.outputStream().use { out ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        total += n
                        if (total > maxBytes) throw CmdError("file_too_large", "文件超过 ${maxBytes / 1024 / 1024}MB")
                        out.write(buf, 0, n)
                    }
                }
            }
            if (total == 0L) throw CmdError("empty_file", "下载到的文件是空的")
            if (!tmp.renameTo(dest)) throw CmdError("save_failed", "保存文件失败")
        } finally {
            tmp.delete()
            conn.disconnect()
        }
    }

    private fun request(method: String, url: String, token: String, body: String?): HttpResult {
        val conn = open(url)
        try {
            conn.requestMethod = method
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = TIMEOUT_MS
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.setRequestProperty("Accept", "application/json")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..399) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            return HttpResult(code, text)
        } finally {
            conn.disconnect()
        }
    }
}
