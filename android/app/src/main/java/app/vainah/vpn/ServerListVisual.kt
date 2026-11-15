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
 * Unified light server-list design. The country, protocol and TCP observation
 * come only from the real imported subscription; no invented ping or endpoints.
 */
object ServerListVisual {
    private val ink = VainahDesign.ink
    private val muted = VainahDesign.muted
    private val accent = VainahDesign.purple
    private val line = VainahDesign.border
    private val plain = VainahDesign.surface
    private val chosen = Color.rgb(241, 242, 252)

    fun backgroundColor(): Int = VainahDesign.background
    fun textColor(): Int = ink
    fun mutedColor(): Int = muted
    fun accentColor(): Int = accent
    fun cardColor(): Int = plain

    private fun dp(context: Context, size: Int): Int =
        (context.resources.displayMetrics.density * size).toInt()

    private fun shape(context: Context, color: Int, radius: Int): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(context, radius).toFloat()
        }

    fun sheet(context: Context): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        background = shape(context, plain, 23).apply {
            setStroke(dp(context, 1), VainahDesign.border)
        }
        setPadding(dp(context, 12), dp(context, 13), dp(context, 12), dp(context, 15))
        elevation = dp(context, 1).toFloat()
    }

    fun row(
        context: Context,
        info: ServerRowInfo,
        latency: String,
        isSelected: Boolean,
        isFavorite: Boolean = false,
        isWhitelist: Boolean = false,
        onFavoriteClick: (() -> Unit)? = null,
        onClick: () -> Unit,
    ): View {
        val color = if (isSelected) chosen else plain
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            minimumHeight = dp(context, if (isWhitelist) 74 else 69)
            background = RippleDrawable(
                ColorStateList.valueOf(Color.argb(35, 111, 111, 177)),
                shape(context, color, 13).apply {
                    if (isSelected) setStroke(dp(context, 1), VainahDesign.softPurple)
                },
                null
            )
        }

        val marker = View(context).apply {
            background = shape(context, if (isSelected) accent else color, 3)
        }
        content.addView(marker, LinearLayout.LayoutParams(
            dp(context, 3), dp(context, 54)
        ))
        val flag = TextView(context).apply {
            text = info.flag
            textSize = 25f
            gravity = Gravity.CENTER
        }
        content.addView(flag, LinearLayout.LayoutParams(
            dp(context, 44), -2
        ).apply { marginStart = dp(context, 6); marginEnd = dp(context, 5) })

        val labels = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
        }
        labels.addView(TextView(context).apply {
            text = info.title
            textSize = 14.5f
            typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
            setTextColor(ink)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        })
        labels.addView(TextView(context).apply {
            text = info.subtitle
            textSize = 10.5f
            setTextColor(muted)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        }, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(context, 3)
        })
        if (isWhitelist) {
            labels.addView(TextView(context).apply {
                text = "Белые списки · группа"
                textSize = 9.5f
                setTextColor(VainahDesign.green)
                maxLines = 1
            }, LinearLayout.LayoutParams(-1, -2).apply {
                topMargin = dp(context, 2)
            })
        }
        content.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))

        val shortLatency = when {
            latency.startsWith("TCP ") -> latency.removePrefix("TCP ")
            latency == "—" -> "—"
            else -> latency
        }
        val ping = TextView(context).apply {
            text = shortLatency
            textSize = 10.5f
            setTextColor(if (latency.startsWith("TCP ")) VainahDesign.green else muted)
            gravity = Gravity.END or Gravity.CENTER_VERTICAL
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            contentDescription = "TCP-задержка: " + latency
        }
        content.addView(ping, LinearLayout.LayoutParams(
            dp(context, if (shortLatency == "—") 24 else 68), -2
        ).apply { marginStart = dp(context, 3) })

        if (onFavoriteClick != null) {
            content.addView(TextView(context).apply {
                text = if (isFavorite) "★" else "☆"
                textSize = 21f
                setTextColor(if (isFavorite) accent else muted)
                gravity = Gravity.CENTER
                contentDescription = if (isFavorite)
                    "Убрать из избранного" else "Добавить в избранное"
                isFocusable = true
                isClickable = true
                setOnClickListener { onFavoriteClick() }
            }, LinearLayout.LayoutParams(dp(context, 34), dp(context, 48)))
        }
        content.addView(TextView(context).apply {
            text = "›"
            textSize = 23f
            setTextColor(muted)
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(dp(context, 16), -2))

        content.isClickable = true
        content.isFocusable = true
        content.contentDescription = buildString {
            append(info.title)
            append(", ")
            append(info.subtitle)
            append(", TCP: ")
            append(if (latency == "—") "не измерено" else latency)
            if (isSelected) append(", выбран для следующего подключения")
            if (isFavorite) append(", избранный")
            if (isWhitelist) append(", группа Белые списки")
        }
        content.setOnClickListener { onClick() }
        return content
    }

    fun separator(context: Context): View = View(context).apply {
        setBackgroundColor(line)
        minimumHeight = dp(context, 1)
    }
}
