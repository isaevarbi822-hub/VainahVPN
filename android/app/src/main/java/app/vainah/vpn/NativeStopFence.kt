package app.vainah.vpn

/**
 * Pure session-lifecycle rule. A delayed native-stop callback is allowed to
 * change state only for the still-current foreground service generation.
 *
 * No VPN links or native engine objects are stored here.
 */
object NativeStopFence {
    fun shouldHandle(
        expectedGeneration: Int,
        currentGeneration: Int,
        serviceStarted: Boolean,
        ownsForeground: Boolean
    ): Boolean = expectedGeneration > 0 &&
        expectedGeneration == currentGeneration && serviceStarted && ownsForeground
}
