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
        for(i in 0 until items.length()) {
            val p = items.getJSONObject(i)
            val id = p.getString("id")
            if (!idFormat.matches(id) || !seen.add(id)) continue
            val title = p.getString("title").trim()
            if (title.length !in 1..80 || title.any { it.isISOControl() }) continue
            val days = p.getInt("days")
            val devices = p.getInt("devices")
            if (days !in 1..3650 || devices !in 1..20) continue
            val category = p.optString("category")
            val isTrial = id == "trial-free" && category == "trial"
            if (!isTrial && category !in setOf("personal", "family")) continue
            val price = p.getString("price_rub")
            if (!priceFormat.matches(price)) continue
            if (isTrial && BigDecimal(price).compareTo(BigDecimal.ZERO) != 0) continue
            if (!isTrial && BigDecimal(price) <= BigDecimal.ZERO) continue
            val checkout = p.optBoolean("checkout_supported", false)
            val path = p.optString("checkout_path")
            if (isTrial && (checkout || path != "/trial.html")) continue
            if (!isTrial && (!checkout || path != "/checkout.html?plan=$id")) continue
            val plan = Plan(id, title, days, devices, price, category,
                p.optString("tag").take(46), isTrial, checkout, path)
            if (isTrial) trial = plan else paid.add(plan)
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
