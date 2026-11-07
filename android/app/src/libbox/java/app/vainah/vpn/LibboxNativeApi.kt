package app.vainah.vpn

import io.nekohasekai.libbox.CommandServer
import io.nekohasekai.libbox.CommandServerHandler
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.OverrideOptions
import io.nekohasekai.libbox.PlatformInterface
import io.nekohasekai.libbox.SetupOptions
import android.content.Context
import java.io.File

/**
 * Experimental compile-time adapter to the real libbox Java API.
 * Does not start a tunnel until a reviewed Android PlatformInterface
 * implements openTun, network protection, routing and DNS correctly.
 * Included only with -PvainahEnableLibbox=true.
 */
internal object LibboxNativeApi {
    @Volatile private var initialized = false

    @Synchronized
    fun setup(context: Context) {
        if (initialized) return
        // libbox needs writable base/working/temp paths before NewCommandServer.
        // Its Go setup routine also initializes file ownership and crash logging.
        val base = File(context.filesDir, "libbox").apply { mkdirs() }
        val work = File(base, "work").apply { mkdirs() }
        val temp = File(context.cacheDir, "libbox").apply { mkdirs() }
        check(base.isDirectory && work.isDirectory && temp.isDirectory)
        Libbox.setup(SetupOptions().apply {
            basePath = base.absolutePath
            workingPath = work.absolutePath
            tempPath = temp.absolutePath
            crashReportSource = "android"
            logMaxLines = 1000L
            debug = false
            fixAndroidStack = true
        })
        initialized = true
    }
    fun validateConfiguration(config: String) {
        Libbox.checkConfig(config)
    }

    fun createCommandServer(
        handler: CommandServerHandler,
        platform: PlatformInterface
    ): CommandServer = CommandServer(handler, platform)

    fun start(server: CommandServer, config: String) {
        validateConfiguration(config)
        server.start()
        server.startOrReloadService(config, OverrideOptions())
    }

    fun close(server: CommandServer) {
        try { server.closeService() } finally { server.close() }
    }
}
