package app.vainah.vpn

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Sole owner of subscription refresh in the rewritten UI.
 * Credentials stay in Android Keystore; no logging or external proxy.
 * Stale network replies cannot replace a different subscriber's nodes.
 */
class SubscriptionController(context: Context) {
    private val vault = SecureSubscription(context.applicationContext)
    private val hwid = SubscriptionHwid(context.applicationContext)
    private val main = Handler(Looper.getMainLooper())
    private val generation = AtomicInteger()
    private val inFlight = AtomicBoolean(false)

    val busy: Boolean get() = inFlight.get()

    fun savedLink(): String? = vault.load()
    fun cachedNodes(): List<VainahNode> =
        vault.load()?.let { vault.cachedServers(it) }.orEmpty()

    fun sourceLabel(): String =
        SubscriptionOrigin.label(SubscriptionOrigin.fromLink(vault.load()))

    fun userAgent(): String? = vault.userAgent()
    fun saveUserAgent(value: String): Boolean = vault.saveUserAgent(value)
    fun resetUserAgent() = vault.resetUserAgent()
    fun hwidEnabled(): Boolean = hwid.isEnabled()
    fun setHwidEnabled(value: Boolean): Boolean = hwid.setEnabled(value)

    fun saveLink(value: String): Boolean {
        val valid = SubscriptionInput.validate(value) ?: return false
        invalidate()
        return vault.save(valid)
    }

    fun clear() {
        invalidate()
        vault.delete()
    }

    fun invalidate() {
        generation.incrementAndGet()
        inFlight.set(false)
    }

    /**
     * Returns false if no link or a request is already running.
     * Result callback executes on main thread while this instance is current.
     */
    fun refresh(callback: (Result<List<VainahNode>>) -> Unit): Boolean {
        val link = vault.load() ?: return false
        if (!inFlight.compareAndSet(false, true)) return false
        val request = generation.incrementAndGet()
        val agent = vault.userAgent()
        val approvedHeaders = hwid.requestHeaders()
        Thread({
            val result = runCatching {
                val nodes = SubscriptionServers.loadNodes(link, approvedHeaders, agent)
                // A current, successfully parsed result is eligible for cache.
                if (request == generation.get() && vault.load() == link)
                    vault.saveServerCache(link, nodes)
                nodes
            }
            main.post {
                if (request != generation.get() || vault.load() != link) return@post
                inFlight.set(false)
                callback(result)
            }
        }, "vainah-subscription-refresh").start()
        return true
    }
}
