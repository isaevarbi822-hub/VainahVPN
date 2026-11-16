package app.vainah.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import android.view.View
import kotlin.math.max

/** Pure Canvas chart; it only renders actual fresh libbox measurements. */
class TrafficSparklineView(context: Context) : View(context) {
    private var samples: List<TrafficTimeline.Point> = emptyList()
    private val grid = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(231, 224, 245)
        strokeWidth = 1f
    }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = VainahDesign.purple
        strokeWidth = 3.2f * resources.displayMetrics.density
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val shade = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = VainahDesign.muted
        textSize = resources.displayMetrics.scaledDensity * 11f
    }

    fun show(values: List<TrafficTimeline.Point>) {
        samples = values.takeLast(42)
        contentDescription = if (samples.size < 2)
            "График недоступен: недостаточно измерений libbox"
        else "График реального сетевого трафика, ${samples.size} измерений"
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val density = resources.displayMetrics.density
        val left = 11f * density
        val right = width - 11f * density
        val top = 13f * density
        val bottom = height - 23f * density
        if (right <= left || bottom <= top) return
        for (i in 0..3) {
            val y = top + (bottom - top) * i / 3f
            canvas.drawLine(left, y, right, y, grid)
        }
        if (samples.size < 2) {
            canvas.drawText("История появится после подключения", left,
                bottom - 9f * density, textPaint)
            return
        }
        val peak = max(1L, samples.maxOf { it.combined })
        val first = samples.first().elapsedMs
        val duration = max(1L, samples.last().elapsedMs - first)
        val trace = Path()
        val fill = Path()
        samples.forEachIndexed { index, point ->
            val x = left + (right - left) *
                ((point.elapsedMs - first).toFloat() / duration)
            val y = bottom - (bottom - top) *
                (point.combined.toDouble() / peak.toDouble()).toFloat()
            if (index == 0) {
                trace.moveTo(x, y)
                fill.moveTo(x, bottom)
                fill.lineTo(x, y)
            } else {
                trace.lineTo(x, y)
                fill.lineTo(x, y)
            }
        }
        fill.lineTo(right, bottom)
        fill.close()
        shade.shader = LinearGradient(0f, top, 0f, bottom,
            intArrayOf(Color.argb(105, 162, 113, 229),
                Color.argb(8, 162, 113, 229)), null, Shader.TileMode.CLAMP)
        canvas.drawPath(fill, shade)
        shade.shader = null
        canvas.drawPath(trace, stroke)
        canvas.drawText("libbox · ↓ + ↑", left, height - 6f * density, textPaint)
        val peakText = VpnTrafficStore.format(peak) + "/с"
        canvas.drawText(peakText, right - textPaint.measureText(peakText),
            height - 6f * density, textPaint)
    }
}
