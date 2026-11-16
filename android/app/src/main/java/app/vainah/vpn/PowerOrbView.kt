package app.vainah.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import kotlin.math.min

/**
 * Draw the VPN power symbol as a vector: not every Samsung/Android typeface
 * contains Unicode U+23FB, which previously rendered as a crossed box.
 * Tap handling is supplied by MainActivity and does not fake VPN state.
 */
class PowerOrbView(context: Context) : View(context) {
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = VainahDesign.muted
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val bounds = RectF()

    /** Real service phase controls the symbol color; never fake VPN success. */
    fun setVpnPhase(phase: String) {
        stroke.color = when (phase) {
            VpnConnectionState.TUN_READY, VpnConnectionState.ONLINE -> android.graphics.Color.WHITE
            VpnConnectionState.STARTING -> android.graphics.Color.WHITE
            VpnConnectionState.FAILED -> VainahDesign.error
            else -> if (VainahTheme.isDark) android.graphics.Color.WHITE else VainahDesign.muted
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        val cx = width / 2f
        val cy = height / 2f
        val radius = size * 0.173f
        stroke.strokeWidth = size * 0.036f
        val top = cy - radius
        bounds.set(cx - radius, top, cx + radius, cy + radius)
        // 120-degree gap at top, with a centered power stem.
        canvas.drawArc(bounds, -42f, 264f, false, stroke)
        canvas.drawLine(cx, cy - size * 0.23f, cx, cy + size * 0.015f, stroke)
    }
}
