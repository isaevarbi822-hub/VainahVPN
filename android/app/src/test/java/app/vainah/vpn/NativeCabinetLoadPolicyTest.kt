package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class NativeCabinetLoadPolicyTest {
    @Test fun oneMonotonicDeadlineBoundsAllRequests() {
        val started = 1_000_000_000L
        val deadline = NativeCabinetLoadPolicy.deadlineNanos(started)
        assertEquals(20_000_000_000L, NativeCabinetLoadPolicy.remainingNanos(started, deadline))
        assertEquals(5_000_000_000L,
            NativeCabinetLoadPolicy.remainingNanos(started + 15_000_000_000L, deadline))
        assertEquals(0L,
            NativeCabinetLoadPolicy.remainingNanos(started + 21_000_000_000L, deadline))
    }

    @Test fun expiredRequestsNeverGetExtraWaitingTime() {
        assertEquals(0L, NativeCabinetLoadPolicy.remainingNanos(99L, 98L))
        assertEquals(0L, NativeCabinetLoadPolicy.remainingNanos(99L, 99L))
        assertEquals(1L, NativeCabinetLoadPolicy.remainingNanos(98L, 99L))
    }
}
