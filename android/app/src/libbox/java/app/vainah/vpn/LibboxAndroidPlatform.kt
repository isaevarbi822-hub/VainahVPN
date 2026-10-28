package app.vainah.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.system.OsConstants
import android.net.VpnService
import android.os.ParcelFileDescriptor
import io.nekohasekai.libbox.*
import java.net.NetworkInterface as JavaNetworkInterface

/**
 * Complete, typed bridge for the libbox 1.14.0 PlatformInterface contract.
 * A missing callback must not throw through Go's JNI interface unexpectedly.
 */
internal class LibboxAndroidPlatform(
    private val service: VpnService,
    private val onStage: (String) -> Unit
) : PlatformInterface {
    private val connectivity = service.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    @Volatile private var tun: ParcelFileDescriptor? = null
    private var callback: ConnectivityManager.NetworkCallback? = null
    @Volatile private var interfaceListener: InterfaceUpdateListener? = null

    override fun localDNSTransport(): LocalDNSTransport? = null
    override fun usePlatformAutoDetectInterfaceControl(): Boolean = true
    override fun autoDetectInterfaceControl(fd: Int) {
        check(service.protect(fd)) { "Cannot protect upstream socket from VPN recursion" }
    }
    override fun useProcFS(): Boolean = false
    override fun underNetworkExtension(): Boolean = false
    override fun includeAllNetworks(): Boolean = false
    override fun usePlatformShell(): Boolean = false
    override fun usePlatformBridge(): Boolean = false

    override fun openTun(options: TunOptions): Int {
        check(tun == null) { "TUN already opened" }
        onStage("opening_android_tun")
        check(VpnService.prepare(service) == null) { "Android VPN consent revoked" }
        val mtu = options.mtu.takeIf { it in 1280..9000 } ?: 1500
        val builder = service.Builder().setSession("Vainah VPN")
            .setMtu(mtu)
        // Official sing-box Android (SFA) keeps Android's default
        // non-blocking VPN file descriptor. Forcing blocking I/O can stall
        // the native TUN packet pump despite Android reporting a VPN profile.
        if (android.os.Build.VERSION.SDK_INT >= 29) builder.setMetered(false)

        // Never invent Android tunnel addresses: use the actual libbox inbound.
        val fallbackVirtualDns = mutableListOf<String>()
        val ipv4 = options.inet4Address
        var hasV4 = false
        while (ipv4.hasNext()) {
            val prefix = ipv4.next()
            builder.addAddress(prefix.address(), prefix.prefix())
            // sing-box 1.14 derives the virtual DNS from TUN prefix when
            // options.dnsServerAddress is absent. Never invent public DNS.
            TunDnsFallback.nextAddress(prefix.address(), prefix.prefix())
                ?.let { fallbackVirtualDns.add(it) }
            hasV4 = true
        }
        val ipv6 = options.inet6Address
        var hasV6 = false
        while (ipv6.hasNext()) {
            val prefix = ipv6.next()
            builder.addAddress(prefix.address(), prefix.prefix())
            TunDnsFallback.nextAddress(prefix.address(), prefix.prefix())
                ?.let { fallbackVirtualDns.add(it) }
            hasV6 = true
        }
        check(hasV4 || hasV6) { "No libbox TUN address" }
        if (options.autoRoute) {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                val v4routes = options.inet4RouteAddress
                if (v4routes.hasNext()) {
                    while (v4routes.hasNext()) {
                        val route = v4routes.next()
                        builder.addRoute(route.address(), route.prefix())
                    }
                } else if (hasV4) builder.addRoute("0.0.0.0", 0)
                val v6routes = options.inet6RouteAddress
                if (v6routes.hasNext()) {
                    while (v6routes.hasNext()) {
                        val route = v6routes.next()
                        builder.addRoute(route.address(), route.prefix())
                    }
                } else if (hasV6) builder.addRoute("::", 0)
                val ex4 = options.inet4RouteExcludeAddress
                while (ex4.hasNext()) {
                    val prefix = ex4.next()
                    builder.excludeRoute(android.net.IpPrefix(java.net.InetAddress.getByName(prefix.address()), prefix.prefix()))
                }
                val ex6 = options.inet6RouteExcludeAddress
                while (ex6.hasNext()) {
                    val prefix = ex6.next()
                    builder.excludeRoute(android.net.IpPrefix(java.net.InetAddress.getByName(prefix.address()), prefix.prefix()))
                }
            } else {
                // On Android 8–12, libbox exposes route *ranges*. When an
                // auto-route family is absent, add a full-tunnel route
                // rather than establishing a TUN that captures no traffic.
                val routes4 = options.inet4RouteRange
                var ipv4RouteCount = 0
                while (routes4.hasNext()) {
                    val route = routes4.next()
                    builder.addRoute(route.address(), route.prefix())
                    ipv4RouteCount++
                }
                if (TunRoutePolicy.needsDefaultRoute(options.autoRoute, hasV4, ipv4RouteCount)) {
                    builder.addRoute("0.0.0.0", 0)
                }
                val routes6 = options.inet6RouteRange
                var ipv6RouteCount = 0
                while (routes6.hasNext()) {
                    val route = routes6.next()
                    builder.addRoute(route.address(), route.prefix())
                    ipv6RouteCount++
                }
                if (TunRoutePolicy.needsDefaultRoute(options.autoRoute, hasV6, ipv6RouteCount)) {
                    builder.addRoute("::", 0)
                }
            }
        }
        // The OS resolver must target the virtual DNS configured by
        // sing-box, never an unrelated public IP on the physical network.
        val dns = runCatching { options.dnsServerAddress }.getOrNull()
        var dnsFound = false
        while (dns?.hasNext() == true) {
            val providedAddress = dns.next()
            if (providedAddress.isNotBlank()) {
                builder.addDnsServer(providedAddress)
                dnsFound = true
            }
        }
        if (!dnsFound) {
            check(fallbackVirtualDns.isNotEmpty()) {
                "TUN virtual DNS unavailable: refusing unsafe fallback"
            }
            fallbackVirtualDns.distinct().forEach { builder.addDnsServer(it) }
        }

        val fd = builder.establish() ?: error("Android denied TUN")
        tun = fd
        // The default-interface monitor may already have started. Attach the
        // current physical underlay immediately, not only after the next
        // Wi-Fi/cellular callback arrives.
        interfaceListener?.let { updateDefault(it) }
        onStage("android_tun_established")
        // libbox duplicates this descriptor and we retain our copy to close on stop.
        return fd.fd
    }

    override fun startDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        interfaceListener = listener
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { updateDefault(listener) }
            override fun onLost(network: Network) { updateDefault(listener) }
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                // React when mobile data validates before the old Wi-Fi drops.
                updateDefault(listener)
            }
            override fun onLinkPropertiesChanged(network: Network, props: android.net.LinkProperties) {
                updateDefault(listener)
            }
        }
        connectivity.registerNetworkCallback(request, cb)
        callback = cb
        updateDefault(listener)
    }

    @Synchronized
    private fun updateDefault(listener: InterfaceUpdateListener) {
        // A VPN network must never become its own upstream.
        val candidates = connectivity.allNetworks.filter { network ->
            val caps = connectivity.getNetworkCapabilities(network)
            caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true &&
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) &&
                connectivity.getLinkProperties(network)?.interfaceName != null
        }
        val network = candidates.firstOrNull { net ->
            connectivity.getNetworkCapabilities(net)?.hasCapability(
                NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
        } ?: candidates.firstOrNull()
        val name = network?.let { connectivity.getLinkProperties(it)?.interfaceName }
        val index = name?.let { JavaNetworkInterface.getByName(it)?.index } ?: -1
        // isActiveNetworkMetered reflects the Android default (possibly the
        // VPN), not necessarily the physical interface libbox will dial on.
        val metered = network?.let {
            connectivity.getNetworkCapabilities(it)?.hasCapability(
                NetworkCapabilities.NET_CAPABILITY_NOT_METERED) != true
        } ?: false
        // Notify libbox and Android of the new physical underlay. The app
        // never binds its own upstream to Android's VPN tunnel (tun0).
        if (hasTun()) {
            runCatching {
                service.setUnderlyingNetworks(if (network == null) emptyArray()
                    else arrayOf(network))
            }
        }
        listener.updateDefaultInterface(name.orEmpty(), index, metered, false)
    }

    override fun closeDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        if (interfaceListener === listener) interfaceListener = null
        callback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        callback = null
    }

    override fun getInterfaces(): NetworkInterfaceIterator {
        // Match physical Android Network interfaces and their real DNS/gateways.
        // Enumerating every Java interface included tun0 and confused auto-routing.
        val items = mutableListOf<io.nekohasekai.libbox.NetworkInterface>()
        for (network in connectivity.allNetworks) {
            val props = connectivity.getLinkProperties(network) ?: continue
            val caps = connectivity.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            val name = props.interfaceName ?: continue
            val itf = JavaNetworkInterface.getByName(name) ?: continue
            val obj = io.nekohasekai.libbox.NetworkInterface().apply {
                index = itf.index
                this.name = name
                mtu = itf.mtu.coerceAtLeast(1280)
                flags = (if (itf.isUp) OsConstants.IFF_UP or OsConstants.IFF_RUNNING else 0) or
                    (if (itf.isLoopback) OsConstants.IFF_LOOPBACK else 0) or
                    (if (itf.isPointToPoint) OsConstants.IFF_POINTOPOINT else 0) or
                    (if (itf.supportsMulticast()) OsConstants.IFF_MULTICAST else 0)
                type = when {
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> Libbox.InterfaceTypeWIFI
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> Libbox.InterfaceTypeCellular
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> Libbox.InterfaceTypeEthernet
                    else -> Libbox.InterfaceTypeOther
                }
                addresses = strings(itf.interfaceAddresses.mapNotNull { address ->
                    val host = address.address?.hostAddress?.substringBefore('%') ?: return@mapNotNull null
                    "$host/${address.networkPrefixLength}"
                })
                dnsServer = strings(props.dnsServers.mapNotNull { it.hostAddress })
                gateway = strings(props.routes.filter {
                    it.destination?.prefixLength == 0 && it.gateway?.isAnyLocalAddress == false
                }.mapNotNull { it.gateway?.hostAddress })
                metered = !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
            }
            items.add(obj)
        }
        val iterator = items.iterator()
        return object : NetworkInterfaceIterator {
            override fun hasNext() = iterator.hasNext()
            override fun next() = iterator.next()
        }
    }

    private fun strings(values: List<String>): StringIterator {
        val iterator = values.iterator()
        return object : StringIterator {
            override fun hasNext(): Boolean = iterator.hasNext()
            override fun next(): String = iterator.next()
            override fun len(): Int = values.size
        }
    }

    override fun readWIFIState(): WIFIState? = null
    override fun clearDNSCache() = Unit
    override fun registerMyInterface(name: String) = Unit
    override fun sendNotification(notification: Notification) = Unit
    override fun cancelNotification(identifier: String, typeID: Int) = Unit
    override fun startNeighborMonitor(listener: NeighborUpdateListener) = Unit
    override fun closeNeighborMonitor(listener: NeighborUpdateListener) = Unit
    override fun findConnectionOwner(
        ipProtocol: Int, sourceAddress: String, sourcePort: Int,
        destinationAddress: String, destinationPort: Int
    ): ConnectionOwner = throw UnsupportedOperationException("Per-app routing is not available")
    override fun lookupSFTPServer(): String = throw UnsupportedOperationException("SFTP disabled")
    override fun readSystemSSHHostKey(): String = throw UnsupportedOperationException("SSH disabled")
    override fun tailscaleHostname(): String = ""
    override fun checkPlatformShell(): Unit = throw UnsupportedOperationException("Shell disabled")
    override fun lookupUser(username: String): PlatformUser =
        throw UnsupportedOperationException("User lookup disabled")
    override fun openShellSession(
        user: PlatformUser, command: String, environ: StringIterator,
        term: String, rows: Int, cols: Int
    ): ShellSession = throw UnsupportedOperationException("Shell disabled")
    override fun createBridge(options: BridgeOptions): BridgeSession =
        throw UnsupportedOperationException("Bridge disabled")

    fun hasTun(): Boolean = tun != null

    fun close() {
        interfaceListener = null
        callback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        callback = null
        runCatching { tun?.close() }
        tun = null
    }
}
