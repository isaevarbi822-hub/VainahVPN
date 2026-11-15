package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

/** No native engine or network is needed for these safety contracts. */
class NativeRecoveryPolicyTest {
    @Test fun onlyPreviouslyStartedTunnelCanRecover() {
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.OFF, 0, true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.STARTING, 0, true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.FAILED, 0, true))
        assertTrue(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.TUN_READY, 0, true))
        assertTrue(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.ONLINE, 1, true))
    }

    @Test fun engineCanRetrySecondTimeDuringRecoveryButNeverThird() {
        assertTrue(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.STARTING, 1, true, recovering = true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.STARTING, 2, true, recovering = true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.STARTING, 0, true, recovering = false))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.STARTING, 1, false, recovering = true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.OFF, 0, true, recovering = true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.FAILED, 0, true, recovering = true))
    }

    @Test fun noSecretsOrUserSessionMeansNoAutoreconnect() {
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.TUN_READY, 0, false))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.ONLINE, 1, false))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.TUN_READY, 2, true))
        assertFalse(NativeRecoveryPolicy.shouldRetry(
            VpnConnectionState.TUN_READY, 10, true))
        assertEquals(2, NativeRecoveryPolicy.MAX_RETRIES)
    }

    @Test fun backoffIsBoundedAndNeverAnInfiniteLoop() {
        assertEquals(1_500L, NativeRecoveryPolicy.retryDelayMs(1))
        assertEquals(5_000L, NativeRecoveryPolicy.retryDelayMs(2))
        assertEquals(0L, NativeRecoveryPolicy.retryDelayMs(3))
        assertEquals(0L, NativeRecoveryPolicy.retryDelayMs(-1))
    }
}
