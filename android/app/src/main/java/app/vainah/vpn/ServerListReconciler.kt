package app.vainah.vpn

/**
 * In-memory server list reconciliation.
 *
 * VLESS URIs are bearer credentials. Never log them, persist them in plain
 * preferences, or expose them in view labels. Exact URI equality prevents
 * a changed/rotated credential from silently selecting the wrong server.
 */
object ServerListReconciler {
    fun unique(nodes: List<VainahNode>): List<VainahNode> =
        nodes.distinctBy { it.uri }

    fun preserve(previous: VainahNode?, current: List<VainahNode>): VainahNode? {
        if (previous == null) return null
        return current.firstOrNull { it.uri == previous.uri }
    }
}
