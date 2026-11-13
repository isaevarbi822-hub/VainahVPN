package app.vainah.vpn

import android.app.Application

/** Clerk is opt-in until its Native API and public key are configured. */
class VainahApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!BuildConfig.VAINAH_CLERK_ENABLED ||
            !ClerkPublicKey.isConfigured(BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY)) return
        runCatching {
            val bridge=Class.forName("app.vainah.vpn.ClerkTokenProvider")
            bridge.getMethod("initialize",Application::class.java).invoke(null,this)
        }
    }
}
