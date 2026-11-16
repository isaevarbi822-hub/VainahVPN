package app.vainah.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.SweepGradient
import android.graphics.Typeface
import android.view.View
import kotlin.math.min

/**
 * Original neon power dial, drawn directly in Android instead of an image.
 * The displayed tunnel phase comes exclusively from VpnConnectionState.
 * A visible Android TUN does not prove protected browser egress.
 */
class PowerOrbView(context: Context) : View(context) {
    private val brush = Paint(Paint.ANTI_ALIAS_FLAG)
    private val arc = RectF()
    private var phase: String = VpnConnectionState.OFF

    fun setVpnPhase(next: String) {
        if (next != phase) {
            phase = next
            contentDescription = when (phase) {
                VpnConnectionState.ONLINE, VpnConnectionState.TUN_READY ->
                    "Туннель создан, доступ в интернет не подтверждён. Нажми чтобы отключить"
                VpnConnectionState.STARTING -> "VPN подключается"
                else -> "Включить VPN"
            }
            invalidate()
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        if (size <= 0f) return
        val cx = width / 2f
        val cy = height / 2f
        val connected = phase == VpnConnectionState.ONLINE ||
            phase == VpnConnectionState.TUN_READY
        val starting = phase == VpnConnectionState.STARTING

        // Ambient violet radiance reaches the full bounds of the view.
        brush.reset()
        brush.isAntiAlias = true
        brush.shader = RadialGradient(cx, cy, size * 0.50f,
            intArrayOf(Color.argb(190, 105, 30, 213),
                Color.argb(87, 115, 56, 230),
                Color.argb(0, 95, 30, 196)),
            floatArrayOf(0.40f, 0.72f, 1f), Shader.TileMode.CLAMP)
        canvas.drawCircle(cx, cy, size * 0.50f, brush)

        // Continuous illuminated bezel, with a subtle asymmetric highlight.
        brush.reset()
        brush.isAntiAlias = true
        brush.style = Paint.Style.STROKE
        brush.strokeWidth = size * 0.035f
        brush.shader = SweepGradient(cx, cy,
            intArrayOf(Color.rgb(97, 42, 191), Color.rgb(215, 157, 255),
                Color.rgb(98, 50, 229), Color.rgb(176, 96, 255),
                Color.rgb(97, 42, 191)), null)
        canvas.drawCircle(cx, cy, size * 0.387f, brush)

        brush.reset()
        brush.isAntiAlias = true
        brush.style = Paint.Style.STROKE
        brush.strokeWidth = size * 0.006f
        brush.color = Color.argb(130, 235, 199, 255)
        canvas.drawCircle(cx, cy, size * 0.357f, brush)

        // No light-mode white disc: the center stays legibly purple.
        brush.reset()
        brush.isAntiAlias = true
        brush.shader = RadialGradient(
            cx - size * 0.12f, cy - size * 0.16f,
            size * 0.66f,
            intArrayOf(Color.rgb(195, 113, 255), Color.rgb(126, 51, 224),
                Color.rgb(59, 21, 119)),
            floatArrayOf(0f, 0.50f, 1f), Shader.TileMode.CLAMP
        )
        canvas.drawCircle(cx, cy, size * 0.346f, brush)

        // A couple of thin light arcs give the ring motion, without fake data.
        brush.reset()
        brush.isAntiAlias = true
        brush.style = Paint.Style.STROKE
        brush.strokeCap = Paint.Cap.ROUND
        brush.strokeWidth = size * 0.012f
        brush.color = Color.argb(225, 232, 171, 255)
        arc.set(cx - size * 0.402f, cy - size * 0.402f,
            cx + size * 0.402f, cy + size * 0.402f)
        canvas.drawArc(arc, -130f, 62f, false, brush)
        brush.color = Color.argb(175, 162, 110, 255)
        canvas.drawArc(arc, 45f, 76f, false, brush)

        // Power icon, always high-contrast and rendered as a vector.
        brush.reset()
        brush.isAntiAlias = true
        brush.color = Color.WHITE
        brush.style = Paint.Style.STROKE
        brush.strokeCap = Paint.Cap.ROUND
        brush.strokeWidth = size * 0.022f
        val glyphY = cy - size * 0.047f
        val radius = size * 0.078f
        arc.set(cx - radius, glyphY - radius, cx + radius, glyphY + radius)
        canvas.drawArc(arc, -43f, 266f, false, brush)
        canvas.drawLine(cx, glyphY - size * 0.112f, cx,
            glyphY + size * 0.006f, brush)

        // Status labels are driven by observed service phase, never fake ping.
        brush.reset()
        brush.isAntiAlias = true
        brush.color = Color.WHITE
        brush.style = Paint.Style.FILL
        brush.typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        brush.textAlign = Paint.Align.CENTER
        brush.textSize = size * 0.058f
        val label = when {
            starting -> "ПОДКЛЮЧЕНИЕ"
            connected -> "ТУННЕЛЬ СОЗДАН"
            phase == VpnConnectionState.FAILED -> "ОШИБКА"
            else -> "ПОДКЛЮЧИТЬ"
        }
        canvas.drawText(label, cx, cy + size * 0.165f, brush)
    }
}
