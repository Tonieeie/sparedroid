package io.github.tonieeie.wecomdroid

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.util.UUID

/**
 * 落盘的发件箱。手机看到的每件事先写进这里，再由 [Uploader] 慢慢送给服务器；
 * 服务器确认收到才删。网络断一晚上、App 被杀重启，消息都不会丢。
 *
 * 每条事件带 event_id（UUID），服务器按它去重 —— 上传成功但回包丢了的那批会被重发，
 * 服务器必须能吃下重复。
 */
class EventQueue private constructor(ctx: Context) :
    SQLiteOpenHelper(ctx.applicationContext, "outbox.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE outbox (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "type TEXT NOT NULL," +
                "body TEXT NOT NULL," +
                "created_at INTEGER NOT NULL)"
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun enqueue(type: String, payload: JSONObject, deviceId: String) {
        val now = System.currentTimeMillis()
        val body = JSONObject().apply {
            put("event_id", UUID.randomUUID().toString())
            put("type", type)
            put("device_id", deviceId)
            put("created_at", now)
            put("payload", payload)
        }
        synchronized(this) {
            writableDatabase.insert("outbox", null, ContentValues().apply {
                put("type", type)
                put("body", body.toString())
                put("created_at", now)
            })
            trim()
        }
        Uploader.wake()
    }

    /** 最早的一批，按入队顺序。 */
    fun peek(limit: Int): List<Pair<Long, JSONObject>> = synchronized(this) {
        readableDatabase.rawQuery(
            "SELECT id, body FROM outbox ORDER BY id LIMIT ?", arrayOf(limit.toString())
        ).use { c ->
            buildList {
                while (c.moveToNext()) add(c.getLong(0) to JSONObject(c.getString(1)))
            }
        }
    }

    fun delete(ids: List<Long>) {
        if (ids.isEmpty()) return
        synchronized(this) {
            writableDatabase.execSQL(
                "DELETE FROM outbox WHERE id IN (${ids.joinToString(",")})"
            )
        }
    }

    fun count(): Int = synchronized(this) {
        readableDatabase.rawQuery("SELECT COUNT(*) FROM outbox", null).use { c ->
            c.moveToFirst(); c.getInt(0)
        }
    }

    /**
     * 防止断网太久把手机存储撑爆。先丢侦察用的界面导出（体积大、可再生），
     * 真实消息尽量留着。
     */
    private fun trim() {
        val n = count()
        if (n <= MAX_ROWS) return
        val db = writableDatabase
        db.execSQL(
            "DELETE FROM outbox WHERE id IN (SELECT id FROM outbox WHERE type = 'ui_dump' " +
                "ORDER BY id LIMIT ${n - MAX_ROWS})"
        )
        val left = count()
        if (left > MAX_ROWS) {
            db.execSQL(
                "DELETE FROM outbox WHERE id IN (SELECT id FROM outbox ORDER BY id LIMIT ${left - MAX_ROWS})"
            )
            Status.error("发件箱超过 $MAX_ROWS 条，已丢弃最早的消息 —— 服务器长时间不可达")
        }
    }

    companion object {
        private const val MAX_ROWS = 20000

        @Volatile private var instance: EventQueue? = null
        fun get(ctx: Context): EventQueue =
            instance ?: synchronized(this) { instance ?: EventQueue(ctx).also { instance = it } }
    }
}
