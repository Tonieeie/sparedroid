package io.github.tonieeie.sparedroid

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * 把企业微信当前界面的控件树变成 JSON。
 *
 * 两种形态：
 *  - [tree]：完整树，侦察用。拿到后在电脑上看，摸清新版企业微信的界面结构。
 *  - [flat]：只保留有文字的节点，按屏幕从上到下的遍历顺序 —— 读聊天内容用，体积小。
 *
 * 字段：cls 控件类型（短名）、text、desc（无障碍描述）、id（资源 ID）、
 * b 屏幕坐标 "左,上,右,下"、f 标志（c 可点 / l 可长按 / e 可编辑 / s 可滚动 / h 不可见）。
 */
object TreeDumper {
    private const val MAX_NODES = 3000

    fun tree(root: AccessibilityNodeInfo): JSONObject {
        val counter = intArrayOf(0)
        return node(root, counter) ?: JSONObject()
    }

    private fun node(n: AccessibilityNodeInfo, counter: IntArray): JSONObject? {
        if (counter[0]++ >= MAX_NODES) return null
        val o = describe(n)
        val kids = JSONArray()
        for (i in 0 until n.childCount) {
            val c = n.getChild(i) ?: continue
            node(c, counter)?.let { kids.put(it) }
        }
        if (kids.length() > 0) o.put("ch", kids)
        return o
    }

    fun flat(root: AccessibilityNodeInfo): JSONArray {
        val out = JSONArray()
        walk(root) { n ->
            if (!n.text.isNullOrEmpty() || !n.contentDescription.isNullOrEmpty() || n.isEditable) {
                out.put(describe(n))
            }
        }
        return out
    }

    fun walk(root: AccessibilityNodeInfo, visit: (AccessibilityNodeInfo) -> Unit) {
        var count = 0
        fun rec(n: AccessibilityNodeInfo) {
            if (count++ >= MAX_NODES) return
            visit(n)
            for (i in 0 until n.childCount) n.getChild(i)?.let { rec(it) }
        }
        rec(root)
    }

    private fun describe(n: AccessibilityNodeInfo): JSONObject = JSONObject().apply {
        n.className?.let { put("cls", it.toString().substringAfterLast('.')) }
        n.text?.let { put("text", it.toString()) }
        n.contentDescription?.let { put("desc", it.toString()) }
        n.viewIdResourceName?.let { put("id", it) }
        val r = Rect()
        n.getBoundsInScreen(r)
        put("b", "${r.left},${r.top},${r.right},${r.bottom}")
        val f = buildString {
            if (n.isClickable) append('c')
            if (n.isLongClickable) append('l')
            if (n.isEditable) append('e')
            if (n.isScrollable) append('s')
            if (!n.isVisibleToUser) append('h')
        }
        if (f.isNotEmpty()) put("f", f)
    }
}
