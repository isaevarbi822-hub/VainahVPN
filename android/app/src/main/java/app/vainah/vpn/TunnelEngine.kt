package app.vainah.vpn

import android.net.VpnService

/**
 * Adapter for a future H1Cloud/VLESS packet-forwarding engine.
 * No mock or fake success: ready is false until a reviewed transport ships.
 */
interface TunnelEngine {
    val ready: Boolean
    fun connect(service: VpnService, singBoxConfigJson: String): Result<Unit>
    fun disconnect()
}

object UnavailableTunnelEngine : TunnelEngine {
    override val ready = false
    override fun connect(service: VpnService, singBoxConfigJson: String): Result<Unit> =
        Result.failure(UnsupportedOperationException("VLESS engine not integrated"))
    override fun disconnect() = Unit
}

object EngineRegistry {
    // Replace only after VPN egress/DNS/IPv6/leak tests pass.
    val active: TunnelEngine by lazy {
        // The experimental adapter class is excluded from normal APK builds.
        // Never display a connected state when the real engine is absent.
        runCatching {
            Class.forName("app.vainah.vpn.LibboxTunnelEngine")
                .getDeclaredConstructor().newInstance() as TunnelEngine
        }.getOrDefault(UnavailableTunnelEngine)
    }

    private val sessionGate = OwnedTunnelGate()

    fun connectOwned(
        service: VpnService,
        config: String,
        isStillRequested: () -> Boolean
    ): Result<Unit> = sessionGate.connect(
        service,
        isStillRequested,
        open = { active.connect(service, config) },
        close = { active.disconnect() }
    )

    fun disconnectOwned(service: VpnService) = sessionGate.disconnect(service) {
        active.disconnect()
    }
}
