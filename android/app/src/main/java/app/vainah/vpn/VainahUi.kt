package app.vainah.vpn

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Native Android visual system shared by every VainahVPN screen.
 * All status labels must come from caller-supplied real data.
 * No fixed VPN availability, ping, expiry or subscription balance.
 */
object VainahUi {
    fun dp(context: Context, value: Int): Int =
        (context.resources.displayMetrics.density * value + 0.5f).toInt()

    fun pageBackground(): GradientDrawable = GradientDrawable(
        GradientDrawable.Orientation.TL_BR,
        intArrayOf(Color.rgb(251, 249, 255), Color.rgb(243, 239, 252))
    )

    fun cardBackground(context: Context): GradientDrawable = GradientDrawable(
        GradientDrawable.Orientation.TL_BR,
        intArrayOf(Color.WHITE, Color.rgb(252, 249, 255))
    ).apply {
        cornerRadius = dp(context, 24).toFloat()
        setStroke(dp(context, 1), VainahDesign.border)
    }

    fun buttonBackground(context: Context, primary: Boolean): RippleDrawable {
        val fill = if (primary) GradientDrawable(
            GradientDrawable.Orientation.LEFT_RIGHT,
            intArrayOf(VainahDesign.purple, VainahDesign.accentDark)
        ) else GradientDrawable(
            GradientDrawable.Orientation.TL_BR,
            intArrayOf(Color.WHITE, Color.rgb(249, 245, 255))
        )
        fill.apply {
            cornerRadius = dp(context, 17).toFloat()
            if (!primary) setStroke(dp(context, 1), VainahDesign.border)
        }
        return RippleDrawable(
            ColorStateList.valueOf(Color.argb(54, 151, 117, 210)),
            fill, null
        )
    }

    fun chip(context: Context, label: String, selected: Boolean): TextView =
        TextView(context).apply {
            text = label
            textSize = 11f
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            gravity = Gravity.CENTER
            typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
            setTextColor(if (selected) Color.WHITE else VainahDesign.ink)
            setPadding(dp(context, 13), dp(context, 8),
                dp(context, 13), dp(context, 8))
            background = buttonBackground(context, selected)
            minimumHeight = dp(context, 36)
        }

    fun statusPill(
        context: Context, content: String,
        tone: Tone = Tone.NEUTRAL
    ): TextView = TextView(context).apply {
        text = content
        textSize = 11f
        gravity = Gravity.CENTER
        typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        val (textColor, fill) = when (tone) {
            Tone.SUCCESS -> VainahDesign.green to Color.rgb(225, 247, 235)
            Tone.WARNING -> VainahDesign.error to Color.rgb(255, 237, 237)
            Tone.PURPLE -> VainahDesign.purple to Color.rgb(240, 232, 253)
            Tone.NEUTRAL -> VainahDesign.muted to Color.rgb(242, 240, 248)
        }
        setTextColor(textColor)
        background = GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(context, 14).toFloat()
        }
        setPadding(dp(context, 11), dp(context, 7),
            dp(context, 11), dp(context, 7))
    }

    fun infoStrip(context: Context, message: String): TextView =
        TextView(context).apply {
            text = "ⓘ  " + message
            textSize = 11.5f
            setTextColor(VainahDesign.accentDark)
            setLineSpacing(dp(context, 2).toFloat(), 1.02f)
            setPadding(dp(context, 13), dp(context, 11),
                dp(context, 13), dp(context, 11))
            background = GradientDrawable().apply {
                setColor(Color.rgb(241, 234, 254))
                cornerRadius = dp(context, 15).toFloat()
            }
        }

    fun detailRow(
        context: Context, label: String, value: String,
        tone: Tone = Tone.NEUTRAL
    ): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        minimumHeight = dp(context, 44)
        setPadding(dp(context, 10), dp(context, 5),
            dp(context, 10), dp(context, 5))
        background = GradientDrawable().apply {
            setColor(Color.rgb(249, 247, 253))
            cornerRadius = dp(context, 12).toFloat()
        }
        addView(TextView(context).apply {
            text = label
            textSize = 12f
            setTextColor(VainahDesign.ink)
            maxLines = 2
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        addView(statusPill(context, value, tone),
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                marginStart = dp(context, 6)
            })
    }

    enum class Tone { SUCCESS, WARNING, PURPLE, NEUTRAL }
}
