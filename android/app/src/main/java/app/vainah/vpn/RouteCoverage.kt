package app.vainah.vpn

import java.math.BigInteger

/**
 * Computes coverage of the full address family by Android's unicast routes.
 * No DNS resolution, server addresses, or credentials are required.
 *
 * A full prefix set is necessary for a full tunnel, but does not show that
 * the native engine actually forwards packets to the VPN server.
 */
object RouteCoverage {
    fun coversAll(
        familyBytes: Int,
        prefixes: List<Pair<ByteArray, Int>>
    ): Boolean {
        require(familyBytes == 4 || familyBytes == 16)
        val totalBits = familyBytes * 8
        val validRanges = prefixes.mapNotNull { (address, prefix) ->
            if (address.size != familyBytes || prefix !in 0..totalBits) {
                null
            } else {
                val hostBits = totalBits - prefix
                val start = BigInteger(1, address)
                    .shiftRight(hostBits).shiftLeft(hostBits)
                val end = start.add(BigInteger.ONE.shiftLeft(hostBits))
                    .subtract(BigInteger.ONE)
                start to end
            }
        }.sortedWith(compareBy<Pair<BigInteger, BigInteger>> { it.first }
            .thenBy { it.second })

        var coveredUntil = BigInteger.valueOf(-1)
        val fullRangeEnd = BigInteger.ONE.shiftLeft(totalBits)
            .subtract(BigInteger.ONE)
        for ((start, end) in validRanges) {
            if (start > coveredUntil.add(BigInteger.ONE)) return false
            if (end > coveredUntil) coveredUntil = end
            if (coveredUntil >= fullRangeEnd) return true
        }
        return false
    }
}
