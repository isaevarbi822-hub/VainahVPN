package app.vainah.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import android.view.View
import kotlin.math.min

/** Drawn brand mark with no network assets, copyrighted logo or emoji glyph. */
class VainahShieldView(context: Context) : View(context) {
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG)
    private val white = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 1.8f
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        if (size <= 0f) return
        canvas.save()
        canvas.translate((width - size) / 2f, (height - size) / 2f)
        canvas.scale(size / 32f, size / 32f)
        val shield = Path().apply {
            moveTo(16f, 2f)
            lineTo(29f, 6.5f)
            lineTo(28.2f, 18f)
            cubicTo(27.6f, 22.5f, 22.1f, 27.8f, 16f, 31f)
            cubicTo(9.9f, 27.8f, 4.4f, 22.5f, 3.8f, 18f)
            lineTo(3f, 6.5f)
            close()
        }
        ink.style = Paint.Style.FILL
        ink.shader = LinearGradient(3f, 2f, 29f, 31f,
            intArrayOf(Color.rgb(158, 101, 235), Color.rgb(91, 43, 159)),
            null, Shader.TileMode.CLAMP)
        canvas.drawPath(shield, ink)
        ink.shader = null
        val peak = Path().apply {
            moveTo(6f, 21f)
            lineTo(12f, 12f)
            lineTo(16f, 18f)
            lineTo(20f, 11f)
            lineTo(26f, 21f)
        }
        canvas.drawPath(peak, white)
        canvas.restore()
    }
}
