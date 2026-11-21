pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        // Opt-in libbox integration: JitPack is used only with -PvainahEnableLibbox=true.
        if (providers.gradleProperty("vainahEnableLibbox").orNull == "true") {
            maven(url = "https://jitpack.io")
        }
    }
}
rootProject.name = "VainahVPN"
include(":app")
