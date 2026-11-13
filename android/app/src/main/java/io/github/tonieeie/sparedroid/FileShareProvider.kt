package io.github.tonieeie.sparedroid

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File

/**
 * 把 App 自己目录里的文件（只限 files/share/ 下）以只读方式借给企业微信。
 *
 * 安卓不允许直接把文件路径交给别的 App，必须通过 ContentProvider 发 content:// 地址。
 * 通常用 AndroidX 的 FileProvider，但本项目零依赖，这里手写一个最小版本。
 *
 * 企业微信会来查文件名（DISPLAY_NAME）和大小（SIZE）—— 文件名决定群里显示成什么，
 * 所以服务器下发的文件名（如 "报价单_张三.pdf"）原样保留。
 */
class FileShareProvider : ContentProvider() {

    override fun onCreate() = true

    private fun fileFor(uri: Uri): File {
        val ctx = context ?: throw SecurityException("no context")
        val dir = shareDir(ctx).canonicalFile
        val name = uri.lastPathSegment ?: throw SecurityException("no file name")
        val f = File(dir, name).canonicalFile
        // 防 "../" 之类跳出共享目录
        if (f.parentFile != dir || !f.isFile) throw SecurityException("not shareable: $name")
        return f
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (mode != "r") throw SecurityException("read only")
        return ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?,
    ): Cursor {
        val f = fileFor(uri)
        val cols = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val row = cols.map {
            when (it) {
                OpenableColumns.DISPLAY_NAME -> f.name
                OpenableColumns.SIZE -> f.length()
                else -> null
            }
        }
        return MatrixCursor(cols).apply { addRow(row) }
    }

    override fun getType(uri: Uri): String = mimeOf(uri.lastPathSegment ?: "")

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0

    companion object {
        const val AUTHORITY = "io.github.tonieeie.sparedroid.files"

        fun shareDir(ctx: Context): File = File(ctx.filesDir, "share").apply { mkdirs() }

        fun uriFor(file: File): Uri = Uri.parse("content://$AUTHORITY/${Uri.encode(file.name)}")

        fun mimeOf(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
            "pdf" -> "application/pdf"
            "png" -> "image/png"
            "jpg", "jpeg" -> "image/jpeg"
            else -> "application/octet-stream"
        }
    }
}
