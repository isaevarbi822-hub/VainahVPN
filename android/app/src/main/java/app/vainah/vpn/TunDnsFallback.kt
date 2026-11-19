package app.vainah.vpn

import java.net.InetAddress

/**
 * Derive sing-box 1.14's default virtual TUN DNS address: the next IP after
 * the TUN interface address. Never fall back to a public physical DNS server.
 *
 * The next address must remain inside the interface prefix. Fail closed for
 * invalid inputs; the caller must refuse to advertise an invented DNS address.
 */
object TunDnsFallback {
    private val ipv4 = Regex("[0-9]{1,3}(\\.[0-9]{1,3}){3}")
    private val ipv6 = Regex("[0-9A-Fa-f:.]+")

    fun nextAddress(rawAddress: String, prefixLength: Int): String? = runCatching {
        // Only numeric addresses are accepted; never resolve a hostname over
        // an underlying network while configuring the tunnel.
        val input = if (':' in rawAddress) {
            require(rawAddress.matches(ipv6))
            InetAddress.getByName(rawAddress).address
        } else {
            require(rawAddress.matches(ipv4))
            rawAddress.split('.').map { octet ->
                val value = octet.toInt()
                require(value <= 255)
                value.toByte()
            }.toByteArray()
        }
        require(prefixLength in 0..input.size * 8)
        val next = input.copyOf()
        var index = next.lastIndex
        while (index >= 0) {
            val sum = (next[index].toInt() and 0xff) + 1
            next[index] = sum.toByte()
            if (sum <= 255) break
            index--
        }
        require(index >= 0) { "No next address" }

        // Don't take a virtual DNS address outside the tunnel's configured
        // IPv4/IPv6 prefix, e.g. when the interface address is the last host.
        for (bit in 0 until prefixLength) {
            val offset = bit / 8
            val shift = 7 - bit % 8
            require(((input[offset].toInt() ushr shift) and 1) ==
                ((next[offset].toInt() ushr shift) and 1)) { "Next IP exits prefix" }
        }
        InetAddress.getByAddress(next).hostAddress?.substringBefore('%')
    }.getOrNull()
}
