package app.vainah.vpn

import android.app.Application

/** Clerk is opt-in until its Native API and public key are configured. */
class VainahApplication : Application() {
    override fun onConfigurationChanged(newConfig: android.content.res.Configuration) {
        super.onConfigurationChanged(newConfig)
        VainahTheme.initialize(this)
    }

    override fun onCreate() {
        super.onCreate()
        VainahTheme.initialize(this)
        // Keep newly added provider nodes (including labeled LTE profiles)
        // synchronized even when the UI has been closed. Scheduling failures
        // must never prevent opening the VPN app.
        runCatching { SubscriptionAutoSyncScheduler.reconcile(this) }
        if (!BuildConfig.VAINAH_CLERK_ENABLED ||
            !ClerkPublicKey.isConfigured(BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY)) return
        runCatching {
            val bridge=Class.forName("app.vainah.vpn.ClerkTokenProvider")
            bridge.getMethod("initialize",Application::class.java).invoke(null,this)
        }
    }
}
