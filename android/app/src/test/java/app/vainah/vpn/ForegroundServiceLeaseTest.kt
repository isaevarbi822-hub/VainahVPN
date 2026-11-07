package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class ForegroundServiceLeaseTest {
    @Test fun oldServiceCannotClearNewOwner() {
        val lease = ForegroundServiceLease()
        val previous = Any()
        val replacement = Any()
        lease.claim(previous)
        lease.claim(replacement)
        assertFalse(lease.release(previous))
        assertTrue(lease.isCurrent(replacement))
        assertTrue(lease.hasCurrent())
        assertTrue(lease.release(replacement))
        assertFalse(lease.hasCurrent())
    }

    @Test fun releasingUnclaimedOrTwiceIsNoop() {
        val lease = ForegroundServiceLease()
        val old = Any()
        assertFalse(lease.release(old))
        assertFalse(lease.isCurrent(old))
        lease.claim(old)
        assertTrue(lease.release(old))
        assertFalse(lease.release(old))
        assertFalse(lease.hasCurrent())
    }

    @Test fun delayedDestroyFromOldThreadDoesNotRemoveNewInstance() {
        val lease = ForegroundServiceLease()
        val first = Any()
        val next = Any()
        val ready = CountDownLatch(1)
        val releaseOld = CountDownLatch(1)
        var cleared = true
        val previousDestroy = Thread {
            ready.countDown()
            check(releaseOld.await(4, TimeUnit.SECONDS))
            cleared = lease.release(first)
        }
        lease.claim(first)
        previousDestroy.start()
        assertTrue(ready.await(4, TimeUnit.SECONDS))
        lease.claim(next)
        releaseOld.countDown()
        previousDestroy.join(4000)
        assertFalse(previousDestroy.isAlive)
        assertFalse(cleared)
        assertTrue(lease.isCurrent(next))
    }
}
