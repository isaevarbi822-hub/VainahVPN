package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** These are JVM-only race tests; they do not claim internet traffic works. */
class OwnedTunnelGateTest {
    private fun OwnedTunnelGate.start(owner: Any, requested: () -> Boolean = { true },
                                      open: () -> Result<Unit> = { Result.success(Unit) },
                                      close: () -> Unit = {}): Result<Unit> =
        connect(owner, requested, open, close)

    @Test fun cancelledAttemptNeverOpensEngine() {
        val gate = OwnedTunnelGate()
        var opens = 0
        val result = gate.start(Any(), requested = { false }, open = {
            opens++
            Result.success(Unit)
        })
        assertTrue(result.isFailure)
        assertEquals(0, opens)
    }

    @Test fun oldServiceCannotCloseNewServiceTunnel() {
        val gate = OwnedTunnelGate()
        val oldService = Any()
        val newService = Any()
        var stops = 0
        assertTrue(gate.start(oldService).isSuccess)
        gate.disconnect(oldService) { stops++ }
        assertEquals(1, stops)
        assertTrue(gate.start(newService).isSuccess)
        gate.disconnect(oldService) { stops++ }
        assertEquals(1, stops)
        gate.disconnect(newService) { stops++ }
        assertEquals(2, stops)
    }

    @Test fun secondOwnerCannotStealLiveEngineOrStartTwice() {
        val gate = OwnedTunnelGate()
        val first = Any()
        var opens = 0
        val open = {
            opens++
            Result.success(Unit)
        }
        assertTrue(gate.start(first, open = open).isSuccess)
        assertTrue(gate.start(Any(), open = open).isFailure)
        assertTrue(gate.start(first, open = open).isFailure)
        assertEquals(1, opens)
    }

    @Test fun failedOpenDoesNotAcquireOwnership() {
        val gate = OwnedTunnelGate()
        val old = Any()
        val next = Any()
        var stops = 0
        assertTrue(gate.start(old, open = {
            Result.failure(IllegalStateException("engine unavailable"))
        }).isFailure)
        gate.disconnect(old) { stops++ }
        assertEquals(0, stops)
        assertTrue(gate.start(next).isSuccess)
        gate.disconnect(next) { stops++ }
        assertEquals(1, stops)
    }

    @Test fun failedDisconnectDoesNotAllowSecondEngineUntilCleanupRetries() {
        val gate = OwnedTunnelGate()
        val first = Any()
        val next = Any()
        assertTrue(gate.start(first).isSuccess)
        assertThrows(IllegalStateException::class.java) {
            gate.disconnect(first) { throw IllegalStateException("close failed") }
        }
        assertTrue(gate.start(next).isFailure)
        gate.disconnect(first) {}
        assertTrue(gate.start(next).isSuccess)
    }

    @Test fun stopDuringNativeStartRollsBackOpenedTunnelBeforeNewConnect() {
        val gate = OwnedTunnelGate()
        val old = Any()
        val next = Any()
        val openStarted = CountDownLatch(1)
        val allowOpenToFinish = CountDownLatch(1)
        val cancelled = AtomicBoolean(false)
        val closed = AtomicInteger(0)
        var result: Result<Unit>? = null

        val worker = Thread {
            result = gate.start(
                old, requested = { !cancelled.get() },
                open = {
                    openStarted.countDown()
                    check(allowOpenToFinish.await(4, TimeUnit.SECONDS))
                    Result.success(Unit)
                },
                close = { closed.incrementAndGet() }
            )
        }
        worker.start()
        assertTrue(openStarted.await(4, TimeUnit.SECONDS))
        cancelled.set(true)  // VpnService.disconnect invalidates its generation.
        allowOpenToFinish.countDown()
        worker.join(4000)
        assertFalse(worker.isAlive)
        assertTrue(result!!.isFailure)
        assertEquals(1, closed.get())
        assertTrue(gate.start(next).isSuccess)
    }

    @Test fun concurrentConnectAttemptsCannotBothOwnEngine() {
        val gate = OwnedTunnelGate()
        val first = Any()
        val second = Any()
        val startFirst = CountDownLatch(1)
        val continueFirst = CountDownLatch(1)
        val opened = AtomicInteger(0)
        val succeeded = AtomicInteger(0)
        val one = Thread {
            if (gate.start(first, open = {
                startFirst.countDown()
                check(continueFirst.await(4, TimeUnit.SECONDS))
                opened.incrementAndGet()
                Result.success(Unit)
            }).isSuccess) succeeded.incrementAndGet()
        }
        val two = Thread {
            if (gate.start(second, open = {
                opened.incrementAndGet()
                Result.success(Unit)
            }).isSuccess) succeeded.incrementAndGet()
        }
        one.start()
        assertTrue(startFirst.await(4, TimeUnit.SECONDS))
        two.start()
        continueFirst.countDown()
        one.join(4000)
        two.join(4000)
        assertFalse(one.isAlive)
        assertFalse(two.isAlive)
        assertEquals(1, opened.get())
        assertEquals(1, succeeded.get())
    }

    @Test fun cancellationCleanupFailureBlocksOtherOwnersUntilRetry() {
        val gate = OwnedTunnelGate()
        val old = Any()
        val next = Any()
        var checked = 0
        val cancelled = gate.start(
            old,
            requested = { ++checked < 2 },
            close = { throw IllegalStateException("native close refused") }
        )
        assertTrue(cancelled.isFailure)
        assertTrue(gate.start(next).isFailure)
        gate.disconnect(old) {}
        assertTrue(gate.start(next).isSuccess)
    }
}
