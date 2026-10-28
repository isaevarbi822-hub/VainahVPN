package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeCheckoutTest {
    private fun catalog(ready: Boolean = true): String {
        val items = JSONArray()
        VainahPlans.all.forEach { plan ->
            items.put(JSONObject().put("id", plan.id).put("days", plan.days)
                .put("deviceLimit", plan.deviceLimit)
                .put("priceRub", "%.2f".format(java.util.Locale.ROOT, plan.priceRub.toDouble())))
        }
        return JSONObject().put("nativeCheckoutReady", ready).put("plans", items).toString()
    }

    @Test fun onlyServerCanConfirmRealBillingReady() {
        assertTrue(NativeCheckout.parseAvailability(catalog()).permitted)
        assertFalse(NativeCheckout.parseAvailability(catalog(false)).permitted)
    }

    @Test fun invalidCatalogPriceOrPlanBlocksCheckout() {
        val mismatch = JSONObject(catalog())
        mismatch.getJSONArray("plans").getJSONObject(0).put("priceRub", "0.01")
        assertFalse(NativeCheckout.parseAvailability(mismatch.toString()).permitted)
        mismatch.getJSONArray("plans").getJSONObject(0).put("priceRub", "99.00")
        mismatch.getJSONArray("plans").getJSONObject(0).put("id", "not-our-plan")
        assertFalse(NativeCheckout.parseAvailability(mismatch.toString()).permitted)
        assertFalse(NativeCheckout.parseAvailability("{}").permitted)
        assertFalse(NativeCheckout.parseAvailability("not JSON").permitted)
    }

    @Test fun onlyKnownPricesAndSafePlanIdsCanOpenSite() {
        assertEquals(
            "https://vainahvpnbot0.netlify.app/checkout.html?plan=365-family",
            NativeCheckout.checkoutUrl("365-family"))
        assertNull(NativeCheckout.checkoutUrl("not-ours"))
        assertNull(NativeCheckout.checkoutUrl("30&redirect=https://malicious.invalid"))
        assertNull(NativeCheckout.checkoutUrl("../../admin"))
    }
}
