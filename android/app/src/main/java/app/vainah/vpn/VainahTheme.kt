package app.vainah.vpn

import android.content.Context
import android.content.res.Configuration

/**
 * Three actually working appearance modes. Never changes the Android VPN
 * service, account secrets, payment URLs or subscription cache.
 */
object VainahTheme {
    enum class Mode { SYSTEM, LIGHT, DARK }

    private const val PREF = "vainah_appearance_v3"
    @Volatile var isDark: Boolean = false
        private set
    @Volatile var mode: Mode = Mode.LIGHT
        private set

    fun parse(value: String?): Mode =
        Mode.values().firstOrNull { it.name == value } ?: Mode.LIGHT

    fun initialize(context: Context) {
        val selected = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .getString("mode", null)
        mode = parse(selected)
        val systemDark =
            context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
                Configuration.UI_MODE_NIGHT_YES
        isDark = when(mode) {
            Mode.SYSTEM -> systemDark
            Mode.LIGHT -> false
            Mode.DARK -> true
        }
    }

    fun select(context: Context, selected: Mode) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .edit().putString("mode", selected.name).commit()
        initialize(context)
    }

    fun label(option: Mode): String = when(option) {
        Mode.SYSTEM -> "Как в системе"
        Mode.LIGHT -> "Светлая"
        Mode.DARK -> "Тёмная"
    }
}
