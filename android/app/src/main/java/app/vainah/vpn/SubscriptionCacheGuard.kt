package app.vainah.vpn

/**
 * The encrypted cache must never be replaced by an empty/unsupported
 * response. A 200 HTTP status only proves a response arrived, not that
 * the customer's subscription actually contained usable VPN entries.
 */
object SubscriptionCacheGuard {
    fun requireUsable(nodes: List<VainahNode>): List<VainahNode> {
        if (nodes.isEmpty()) throw SubscriptionEmptyResult()
        return nodes
    }
}
