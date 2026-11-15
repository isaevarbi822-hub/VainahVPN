package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

/** Deterministic JVM tests; no VPN service or external server required. */
class StartupRetryPolicyTest {
    @Test fun temporaryWifiFailureGetsExactlyOneRetry() {
        val attempts = AtomicInteger()
        val delays = mutableListOf<Long>()
        val connected = StartupRetryPolicy.execute(
            stillRequested = { true },
            connect = {
                if (attempts.incrementAndGet() == 1) throw VpnStartupNetworkException(
                    VpnStartupNetworkException.Reason.ENDPOINT_UNREACHABLE
                )
                "connected"
            },
            delay = { delays.add(it) }
        )
        assertEquals("connected", connected)
        assertEquals(2, attempts.get())
        assertEquals(listOf(900L), delays)
    }

    @Test fun permanentPhysicalNetworkFailureNeverLoops() {
        val attempts = AtomicInteger()
        assertThrows(VpnStartupNetworkException::class.java) {
            StartupRetryPolicy.execute(
                stillRequested = { true },
                connect = {
                    attempts.incrementAndGet()
                    throw VpnStartupNetworkException(
                        VpnStartupNetworkException.Reason.NO_UNDERLAY
                    )
                },
                delay = {}
            )
        }
        assertEquals(StartupRetryPolicy.MAX_ATTEMPTS, attempts.get())
    }

    @Test fun configErrorsDoNotRepeatAndDoNotDelay() {
        var count = 0
        var delayed = false
        assertThrows(IllegalArgumentException::class.java) {
            StartupRetryPolicy.execute(
                stillRequested = { true },
                connect = {
                    count++
                    throw IllegalArgumentException("invalid VLESS configuration")
                },
                delay = { delayed = true }
            )
        }
        assertEquals(1, count)
        assertFalse(delayed)
    }

    @Test fun cancelledVpnCannotReconnectAfterFirstFailure() {
        var requested = true
        var attempts = 0
        assertThrows(VpnStartupNetworkException::class.java) {
            StartupRetryPolicy.execute(
                stillRequested = { requested },
                connect = {
                    attempts++
                    requested = false
                    throw VpnStartupNetworkException(
                        VpnStartupNetworkException.Reason.ENDPOINT_UNREACHABLE
                    )
                },
                delay = { throw AssertionError("Never delay after user cancelled") }
            )
        }
        assertEquals(1, attempts)
    }

    @Test fun cancellationDuringDelayStopsBeforeSecondNetworkAttempt() {
        var requested = true
        var count = 0
        assertThrows(IllegalStateException::class.java) {
            StartupRetryPolicy.execute(
                stillRequested = { requested },
                connect = {
                    count++
                    throw VpnStartupNetworkException(
                        VpnStartupNetworkException.Reason.ENDPOINT_UNREACHABLE
                    )
                },
                delay = { requested = false }
            )
        }
        assertEquals(1, count)
    }
}
