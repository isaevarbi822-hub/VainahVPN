package app.vainah.vpn

import android.app.Application
import com.clerk.api.Clerk
import com.clerk.api.session.fetchToken
import com.clerk.api.network.serialization.ClerkResult
import kotlinx.coroutines.runBlocking

/** This file only enters the -PvainahEnableClerk=true build. */
object ClerkTokenProvider {
    @JvmStatic
    fun initialize(app:Application) {
        if (ClerkPublicKey.isConfigured(BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY))
            Clerk.initialize(app,publishableKey=BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY)
    }

    @JvmStatic
    fun loggedIn():Boolean = Clerk.userFlow.value!=null && Clerk.sessionFlow.value!=null

    /** Fetch a short-lived Clerk JWT fresh for the server, on a background thread. */
    @JvmStatic
    fun getToken():String? = runBlocking {
        val session=Clerk.sessionFlow.value?:return@runBlocking null
        when(val response=session.fetchToken()) {
            is ClerkResult.Success -> response.value.jwt
            is ClerkResult.Failure -> null
        }
    }
}
