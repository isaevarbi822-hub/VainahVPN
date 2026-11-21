package app.vainah.vpn

/**
 * A full-tunnel fallback is valid only if auto routing is explicitly
 * requested, the tunnel has an address of this IP family, and libbox
 * supplied no routes for that family.
 *
 * The fallback is especially important for Android API 26..32 where
 * libbox supplies range iterators instead of API 33+ route iterators.
 */
object TunRoutePolicy {
    fun needsDefaultRoute(
        autoRoute: Boolean,
        familyAddressPresent: Boolean,
        explicitRouteCount: Int
    ): Boolean {
        require(explicitRouteCount >= 0) { "Invalid route count" }
        return autoRoute && familyAddressPresent && explicitRouteCount == 0
    }
}
