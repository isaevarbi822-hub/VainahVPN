package app.vainah.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View
import kotlin.math.min

/** Small original vector navigation icons. No missing emoji glyphs or extra assets. */
class NavigationGlyphView(
    context: Context,
    private val icon: String,
    selected: Boolean
) : View(context) {
    private val pen = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = if (selected) VainahDesign.purple else VainahDesign.muted
        style = Paint.Style.STROKE
        strokeWidth = 2f
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        val scale = size / 24f
        canvas.save()
        canvas.translate((width - size) / 2f, (height - size) / 2f)
        canvas.scale(scale, scale)
        val path = Path()
        when (icon) {
            "HOME" -> {
                path.moveTo(3f, 11f)
                path.lineTo(12f, 4f)
                path.lineTo(21f, 11f)
                path.moveTo(5.5f, 10.5f)
                path.lineTo(5.5f, 20f)
                path.lineTo(18.5f, 20f)
                path.lineTo(18.5f, 10.5f)
                path.moveTo(10f, 20f)
                path.lineTo(10f, 14f)
                path.lineTo(14f, 14f)
                path.lineTo(14f, 20f)
                canvas.drawPath(path, pen)
            }
            "LOCATIONS" -> {
                canvas.drawRoundRect(RectF(3f, 4f, 21f, 10f), 2f, 2f, pen)
                canvas.drawRoundRect(RectF(3f, 14f, 21f, 20f), 2f, 2f, pen)
                canvas.drawCircle(6.5f, 7f, 0.85f, pen)
                canvas.drawCircle(6.5f, 17f, 0.85f, pen)
                canvas.drawLine(11f, 7f, 18f, 7f, pen)
                canvas.drawLine(11f, 17f, 18f, 17f, pen)
            }
            "SECURITY" -> {
                path.moveTo(12f, 2.8f)
                path.lineTo(20f, 6.5f)
                path.lineTo(20f, 12f)
                path.cubicTo(20f, 17f, 16.3f, 20f, 12f, 22f)
                path.cubicTo(7.7f, 20f, 4f, 17f, 4f, 12f)
                path.lineTo(4f, 6.5f)
                path.close()
                path.moveTo(9f, 12f)
                path.lineTo(11f, 14.2f)
                path.lineTo(15.5f, 9.5f)
                canvas.drawPath(path, pen)
            }
            "ACCOUNT" -> {
                canvas.drawRoundRect(RectF(3f, 5f, 21f, 19f), 3f, 3f, pen)
                canvas.drawLine(3f, 10f, 21f, 10f, pen)
                canvas.drawLine(6.5f, 15f, 11f, 15f, pen)
            }
            else -> {
                canvas.drawCircle(12f, 8f, 4f, pen)
                path.moveTo(4.5f, 21f)
                path.cubicTo(4.5f, 13.8f, 19.5f, 13.8f, 19.5f, 21f)
                canvas.drawPath(path, pen)
            }
        }
        canvas.restore()
    }
}
