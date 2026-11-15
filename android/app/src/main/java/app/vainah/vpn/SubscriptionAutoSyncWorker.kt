package app.vainah.vpn

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * Battery-aware background synchronization of the EXACT HTTPS subscription
 * already authorized by the user. WorkManager runs this at OS-selected times
 * (at least 15 minutes apart, potentially delayed by Doze).
 *
 * No server-side account login, no H1Cloud API impersonation and no tunnel
 * restart. Only validated real nodes are cached encrypted via Android Keystore.
 * Never log links, server credentials, device identifiers or HTTP bodies.
 */
class SubscriptionAutoSyncWorker(
    context: Context, params: WorkerParameters
) : Worker(context, params) {
    override fun doWork(): Result {
        val vault = SecureSubscription(applicationContext)
        val link = vault.load() ?: return Result.success()
        if (SubscriptionInput.isDirectKey(link)) return Result.success()
        // A late job must never replace a newer subscription/account's cache.
        val nodes = runCatching {
            SubscriptionServers.loadNodes(
                link,
                SubscriptionHwid(applicationContext).requestHeaders(),
                vault.userAgent()
            )
        }.getOrElse { return Result.success() }
        if (isStopped || vault.load() != link || nodes.isEmpty())
            return Result.success()
        // No disk write when nothing changed. The same credentials are never
        // re-published or exposed outside the existing authorized subscription.
        if (vault.cachedServers(link) != nodes) vault.saveServerCache(link, nodes)
        return Result.success()
    }
}

object SubscriptionAutoSyncScheduler {
    private const val UNIQUE_NAME = "vainah_https_subscription_background_sync_v1"

    /**
     * One unique periodic job; never one task per individual node. Direct
     * VLESS keys are static and do not result in recurring network requests.
     */
    fun reconcile(context: Context) {
        val app = context.applicationContext
        val manager = WorkManager.getInstance(app)
        val link = SecureSubscription(app).load()
        if (link == null || SubscriptionInput.isDirectKey(link)) {
            manager.cancelUniqueWork(UNIQUE_NAME)
            return
        }
        val job = PeriodicWorkRequestBuilder<SubscriptionAutoSyncWorker>(
            15, TimeUnit.MINUTES
        ).setInitialDelay(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()
        manager.enqueueUniquePeriodicWork(
            UNIQUE_NAME, ExistingPeriodicWorkPolicy.KEEP, job
        )
    }
}
