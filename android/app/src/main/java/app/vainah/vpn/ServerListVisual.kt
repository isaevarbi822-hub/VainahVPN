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

/** Responsive server rows: only real imported nodes and measured TCP delays. */
object ServerListVisual {
    private val ink get() = VainahDesign.ink
    private val muted get() = VainahDesign.muted
    private val accent get() = VainahDesign.purple
    private val line get() = VainahDesign.border

    fun backgroundColor(): Int = VainahDesign.background
    fun textColor(): Int = ink
    fun mutedColor(): Int = muted
    fun accentColor(): Int = accent
    fun cardColor(): Int = VainahDesign.surface

    private fun dp(context: Context, size: Int): Int = VainahUi.dp(context, size)

    fun sheet(context: Context): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        background = VainahUi.cardBackground(context)
        setPadding(dp(context, 10), dp(context, 13),
            dp(context, 10), dp(context, 16))
        elevation = dp(context, 3).toFloat()
    }

    fun row(
        context: Context,
        info: ServerRowInfo,
        latency: String,
        isSelected: Boolean,
        isFavorite: Boolean = false,
        isWhitelist: Boolean = false,
        isConnectable: Boolean = true,
        onFavoriteClick: (() -> Unit)? = null,
        onClick: () -> Unit,
    ): View {
        val selectedTint = VainahDesign.inactive
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            minimumHeight = dp(context, if (!isConnectable || isWhitelist) 84 else 76)
            setPadding(dp(context, 9), dp(context, 8),
                dp(context, 9), dp(context, 8))
            val fill = GradientDrawable().apply {
                setColor(if (isSelected) selectedTint else VainahDesign.surface2)
                cornerRadius = dp(context, 18).toFloat()
                setStroke(dp(context, if (isSelected) 2 else 1),
                    if (isSelected) accent else VainahDesign.border)
            }
            background = RippleDrawable(
                ColorStateList.valueOf(Color.argb(55, 176, 95, 255)),
                fill, null
            )
        }
        if (onFavoriteClick != null) {
            val favorite = TextView(context).apply {
                text = if (isFavorite) "★" else "☆"
                textSize = 22f
                setTextColor(if (isFavorite) accent else muted)
                gravity = Gravity.CENTER
                isClickable = true
                isFocusable = true
                contentDescription = if (isFavorite)
                    "Убрать из избранного" else "Добавить в избранное"
                setOnClickListener { onFavoriteClick() }
            }
            content.addView(favorite, LinearLayout.LayoutParams(
                dp(context, 31), dp(context, 48)
            ))
        }

        content.addView(TextView(context).apply {
            text = info.flag
            textSize = 24f
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(dp(context, 40), -2).apply {
            marginStart = dp(context, 2)
            marginEnd = dp(context, 5)
        })

        val labels = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
        }
        labels.addView(TextView(context).apply {
            text = info.title
            textSize = 14.0f
            typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
            setTextColor(ink)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        })
        labels.addView(TextView(context).apply {
            text = info.subtitle
            textSize = 10.8f
            setTextColor(muted)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        }, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(context, 3)
        })
        if (isWhitelist || !isConnectable) {
            labels.addView(TextView(context).apply {
                text = when {
                    isWhitelist && !isConnectable ->
                        "LTE · формат пока недоступен"
                    isWhitelist -> "LTE · группа в приложении"
                    else -> "Просмотр · формат недоступен"
                }
                textSize = 9.4f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(if (isConnectable) VainahDesign.green else muted)
                maxLines = 1
                ellipsize = TextUtils.TruncateAt.END
            }, LinearLayout.LayoutParams(-1, -2).apply {
                topMargin = dp(context, 2)
            })
        }
        content.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))

        val reliable = latency.startsWith("TCP ")
        val shortDelay = if (reliable) latency.removePrefix("TCP ") else latency
        val delay = TextView(context).apply {
            text = if (shortDelay == "—") "—" else shortDelay
            textSize = 11f
            typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
            setTextColor(if (reliable) VainahDesign.green else muted)
            gravity = Gravity.CENTER
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            background = GradientDrawable().apply {
                setColor(if (VainahTheme.isDark) VainahDesign.surface
                    else if (reliable) Color.rgb(225, 247, 235)
                    else Color.rgb(246, 244, 251))
                cornerRadius = dp(context, 13).toFloat()
            }
            setPadding(dp(context, 5), dp(context, 7),
                dp(context, 5), dp(context, 7))
            contentDescription = "Измеренная TCP-задержка: " + latency
        }
        content.addView(delay, LinearLayout.LayoutParams(
            dp(context, if (reliable) 65 else 57), -2
        ).apply { marginStart = dp(context, 3) })

        content.addView(TextView(context).apply {
            text = "›"
            textSize = 23f
            gravity = Gravity.CENTER
            setTextColor(muted)
        }, LinearLayout.LayoutParams(dp(context, 16), -2).apply {
            marginStart = dp(context, 2)
        })
        content.isClickable = true
        content.isFocusable = true
        content.contentDescription = buildString {
            append(info.title)
            append(", ")
            append(info.subtitle)
            append(", TCP: ")
            append(if (latency == "—") "пока не измерено" else latency)
            if (isFavorite) append(", избранный")
            if (isSelected) append(", выбран для следующего подключения")
            if (isWhitelist) append(", группа LTE-доступ")
            if (!isConnectable) append(", транспорт не поддерживается")
        }
        content.setOnClickListener { onClick() }
        return LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            addView(content, LinearLayout.LayoutParams(-1, -2))
            setPadding(0, dp(context, 3), 0, dp(context, 3))
        }
    }

    fun separator(context: Context): View = View(context).apply {
        setBackgroundColor(line)
        minimumHeight = dp(context, 1)
    }
}
