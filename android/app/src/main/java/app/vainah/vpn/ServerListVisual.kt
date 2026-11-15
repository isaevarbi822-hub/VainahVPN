package app.vainah.vpn

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/**
 * An original, accessible Android server-list row. Uses system country emoji,
 * never third-party app assets or embedded/private server credentials.
 */
object ServerListVisual {
    private val ink = VainahDesign.ink
    private val muted = VainahDesign.muted
    private val accent = VainahDesign.purple
    private val line = VainahDesign.border
    private val selectedTint = Color.rgb(43, 35, 68)
    private val plain = VainahDesign.surface2

    fun backgroundColor(): Int = VainahDesign.background
    fun textColor(): Int = ink
    fun mutedColor(): Int = muted
    fun accentColor(): Int = accent
    fun cardColor(): Int = plain

    private fun dp(context: Context, value: Int) =
        (context.resources.displayMetrics.density * value).toInt()

    private fun block(context: Context, color: Int, radius: Int = 16) =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(context, radius).toFloat()
        }

    fun sheet(context: Context): LinearLayout =
        LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            background = block(context, plain, 26)
            setPadding(dp(context, 8), dp(context, 14), dp(context, 8), dp(context, 18))
            elevation = dp(context, 3).toFloat()
        }

    fun row(
        context: Context,
        info: ServerRowInfo,
        latency: String,
        isSelected: Boolean,
        isFavorite: Boolean = false,
        onFavoriteClick: (() -> Unit)? = null,
        onClick: () -> Unit,
    ): View {
        val full = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            background = block(context, if (isSelected) selectedTint else plain, 13)
        }
        val horizontal = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            minimumHeight = dp(context, 74)
        }
        val marker = View(context).apply {
            background = block(context, if (isSelected) accent else plain, 2)
        }
        horizontal.addView(marker, LinearLayout.LayoutParams(dp(context, 4), dp(context, 63)))
        val flag = TextView(context).apply {
            text = info.flag
            textSize = 29f
            gravity = Gravity.CENTER
        }
        horizontal.addView(flag, LinearLayout.LayoutParams(dp(context, 54), -2).apply {
            marginStart = dp(context, 7)
            marginEnd = dp(context, 6)
        })
        val details = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        val title = TextView(context).apply {
            text = info.title
            textSize = 16.5f
            typeface = Typeface.create("sans-serif", Typeface.BOLD)
            setTextColor(ink)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        }
        val subtitle = TextView(context).apply {
            text = info.subtitle
            textSize = 11.2f
            setTextColor(muted)
            letterSpacing = 0.015f
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        }
        details.addView(title)
        details.addView(subtitle, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(context, 5)
        })
        val markedWhitelist = ServerCollections.isWhiteListLabel(info.title)
        if (markedWhitelist) {
            val providerMark = TextView(context).apply {
                text = "✦ Белый список · метка подписки"
                textSize = 10f
                setTextColor(VainahDesign.softPurple)
                typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
                contentDescription = "Сервер отмечен поставщиком как белый список"
            }
            details.addView(providerMark, LinearLayout.LayoutParams(-1, -2).apply {
                topMargin = dp(context, 6)
            })
        }
        horizontal.addView(details, LinearLayout.LayoutParams(0, -2, 1f))
        val lag = TextView(context).apply {
            text = latency
            textSize = 12f
            setTextColor(if (latency == "н/д") muted else accent)
            gravity = Gravity.END or Gravity.CENTER_VERTICAL
            maxLines = 1
        }
        horizontal.addView(lag, LinearLayout.LayoutParams(
            dp(context, if (latency == "н/д") 34 else 88), -2
        ).apply { marginStart = dp(context, 4) })
        if (onFavoriteClick != null) {
            val star = TextView(context).apply {
                text = if (isFavorite) "★" else "☆"
                textSize = 25f
                setTextColor(if (isFavorite) accent else muted)
                gravity = Gravity.CENTER
                contentDescription = if (isFavorite)
                    "Убрать из избранных" else "Добавить в избранное"
                isClickable = true
                isFocusable = true
                setOnClickListener { onFavoriteClick() }
            }
            horizontal.addView(star, LinearLayout.LayoutParams(
                dp(context, 40), dp(context, 55)
            ))
        }
        val arrow = TextView(context).apply {
            text = "›"
            textSize = 29f
            setTextColor(muted)
            gravity = Gravity.CENTER
        }
        horizontal.addView(arrow, LinearLayout.LayoutParams(dp(context, 24), -2))
        full.addView(horizontal)
        full.isClickable = true
        full.isFocusable = true
        full.contentDescription = buildString {
            append(info.title)
            append(", ")
            append(info.subtitle)
            append(", ")
            append(if (latency == "н/д") "задержка не измерена" else latency)
            if (isSelected) append(", выбран для следующего подключения")
            if (isFavorite) append(", избранное")
            if (markedWhitelist) append(", отмечен как белый список в подписке")
        }
        full.setOnClickListener { onClick() }
        return full
    }

    fun separator(context: Context): View = View(context).apply {
        setBackgroundColor(line)
        minimumHeight = dp(context, 1)
    }
}
