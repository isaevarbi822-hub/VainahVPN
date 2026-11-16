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
    private const val NEON_MIGRATION = "neon_dark_v4_applied"
    @Volatile var isDark: Boolean = false
        private set
    @Volatile var mode: Mode = Mode.DARK
        private set

    fun parse(value: String?): Mode =
        Mode.values().firstOrNull { it.name == value } ?: Mode.DARK

    /** Migrate older lavender installs once; any later explicit choice persists. */
    fun migratedMode(saved: String?, migrated: Boolean): Mode =
        if (migrated) parse(saved) else Mode.DARK

    fun initialize(context: Context) {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val migrated = prefs.getBoolean(NEON_MIGRATION, false)
        mode = migratedMode(prefs.getString("mode", null), migrated)
        if (!migrated) prefs.edit()
            .putString("mode", mode.name)
            .putBoolean(NEON_MIGRATION, true).commit()
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
            .edit().putString("mode", selected.name)
            .putBoolean(NEON_MIGRATION, true).commit()
        initialize(context)
    }

    fun label(option: Mode): String = when(option) {
        Mode.SYSTEM -> "Как в системе"
        Mode.LIGHT -> "Светлая"
        Mode.DARK -> "Тёмная"
    }
}
