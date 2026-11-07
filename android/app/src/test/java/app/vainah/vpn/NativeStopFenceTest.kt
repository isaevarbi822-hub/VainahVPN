package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class NativeStopFenceTest {
    @Test fun nativeStopOfActiveSessionIsHandled() {
        assertTrue(NativeStopFence.shouldHandle(7, 7, true, true))
    }

    @Test fun lateStopFromPreviousConnectionCannotDisableReplacement() {
        assertFalse(NativeStopFence.shouldHandle(7, 8, true, true))
    }

    @Test fun callbacksAfterDisconnectOrServiceReplacementAreIgnored() {
        assertFalse(NativeStopFence.shouldHandle(7, 7, false, true))
        assertFalse(NativeStopFence.shouldHandle(7, 7, true, false))
    }

    @Test fun uninitializedGenerationCannotPublishFailedStatus() {
        assertFalse(NativeStopFence.shouldHandle(0, 0, true, true))
        assertFalse(NativeStopFence.shouldHandle(-1, -1, true, true))
    }
}
