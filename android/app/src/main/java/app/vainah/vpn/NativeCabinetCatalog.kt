package app.vainah.vpn

import org.json.JSONObject
import java.math.BigDecimal

/**
 * Authoritative public catalog. Never reconstruct prices or invent available
 * checkout products offline. Only exact plans provided by the API are shown.
 */
object NativeCabinetCatalog {
    /** Real storefront: browser payment checkout only. */
    const val ORIGIN = "https://vainahvpn.onrender.com"
    /** Real Python backend: all signed-in API requests and OAuth callbacks. */
    const val API_ORIGIN = "https://vainahvpn-python-preview.onrender.com"
    const val CATALOG_ENDPOINT = "/api/site/tariffs"
    const val TRIAL_ENDPOINT = "/api/trial/config"
    const val CHECKOUT_STATUS_ENDPOINT = "/api/shop/config"

    data class Plan(
        val id: String,
        val title: String,
        val days: Int,
        val devices: Int,
        val priceRub: String,
        val category: String,
        val tag: String,
        val trial: Boolean,
        val checkoutSupported: Boolean,
        val checkoutPath: String
    ) {
        val priceLabel: String get() = if (trial) "Бесплатно" else "$priceRub ₽"
        val durationLabel: String get() = when(days) {
            1 -> "1 день"
            in 2..4 -> "$days дня"
            else -> "$days дней"
        }
    }

    data class Snapshot(val trial: Plan?, val paid: List<Plan>) {
        val count: Int get() = paid.size + (if (trial == null) 0 else 1)
    }

    private val idFormat = Regex("^[a-z0-9][a-z0-9-]{0,47}$")
    private val priceFormat = Regex("^[0-9]{1,6}\\.[0-9]{2}$")

    fun parse(raw: String): Snapshot {
        require(raw.length in 1..262_144)
        val root = JSONObject(raw)
        val items = root.getJSONArray("plans")
        require(items.length() in 1..150) { "Catalog empty or too large" }
        val seen = HashSet<String>()
        var trial: Plan? = null
        val paid = ArrayList<Plan>()
        for (i in 0 until items.length()) {
            // One malformed tariff must not hide the remaining valid catalog.
            // Reject invalid checkout and prices *before* reserving its ID,
            // otherwise a bad duplicate could suppress the real plan.
            val plan = runCatching {
                val p = items.optJSONObject(i) ?: return@runCatching null
                val id = p.getString("id")
                if (!idFormat.matches(id)) return@runCatching null
                val title = p.getString("title").trim()
                if (title.length !in 1..80 || title.any { it.isISOControl() })
                    return@runCatching null
                val days = p.getInt("days")
                val devices = p.getInt("devices")
                if (days !in 1..3650 || devices !in 1..20)
                    return@runCatching null
                val category = p.optString("category")
                val isTrial = id == "trial-free" && category == "trial"
                if (!isTrial && category !in setOf("personal", "family"))
                    return@runCatching null
                val price = p.getString("price_rub")
                if (!priceFormat.matches(price)) return@runCatching null
                if (isTrial && BigDecimal(price).compareTo(BigDecimal.ZERO) != 0)
                    return@runCatching null
                if (!isTrial && BigDecimal(price) <= BigDecimal.ZERO)
                    return@runCatching null
                val checkout = p.optBoolean("checkout_supported", false)
                val checkoutPath = p.optString("checkout_path")
                if (isTrial && (checkout || checkoutPath != "/trial.html"))
                    return@runCatching null
                if (!isTrial &&
                    (!checkout || checkoutPath != "/checkout.html?plan=$id"))
                    return@runCatching null
                Plan(id, title, days, devices, price, category,
                    p.optString("tag").filterNot { it.isISOControl() }.take(46),
                    isTrial, checkout, checkoutPath)
            }.getOrNull() ?: continue
            if (!seen.add(plan.id)) continue
            if (plan.trial) trial = plan else paid.add(plan)
        }
        require(paid.isNotEmpty() || trial != null) { "No valid plans" }
        return Snapshot(trial, paid)
    }

    /** Payment only via the server-defined fixed, verified site checkout route. */
    fun checkoutUrl(plan: Plan, checkoutReady: Boolean): String? =
        if (checkoutReady && !plan.trial && plan.checkoutSupported &&
            idFormat.matches(plan.id) &&
            plan.checkoutPath == "/checkout.html?plan=${plan.id}" &&
            priceFormat.matches(plan.priceRub)) ORIGIN + plan.checkoutPath
        else null
}
