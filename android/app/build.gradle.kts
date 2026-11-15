plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose") apply false
}

// External RollyPay checkout is not bundled into Google Play builds.
// The off-Play test build still requires backend checkoutReady=true,
// matching server prices, Telegram authentication and signed webhook.
val clerkEnabled = providers.gradleProperty("vainahEnableClerk").orNull == "true"
val clerkPublishableKey = providers.gradleProperty("vainahClerkPublishableKey").orNull ?: ""
if (clerkEnabled) {
    apply(plugin = "org.jetbrains.kotlin.plugin.compose")
}
val isolatedPreview = providers.gradleProperty("vainahIsolatedPreview").orNull == "true"
val nativeLibboxEnabled = providers.gradleProperty("vainahEnableLibbox").orNull == "true"
// Production APK can opt in to the separately reviewed XHTTP-enabled sing-box-lx
// Android artifact. This must never be true when only stock libbox is bundled.
val xhttpNativeEnabled = nativeLibboxEnabled &&
    providers.gradleProperty("vainahUseXhttpCore").orNull == "true"
val standaloneCheckout = providers.gradleProperty("vainahStandaloneCheckout")
    .orNull == "true"

android {
    namespace = "app.vainah.vpn"
    compileSdk = if (clerkEnabled) 36 else 35

    defaultConfig {
        applicationId = "app.vainah.vpn.next"
        manifestPlaceholders["vainahAppLabel"] = "VainahVPN"
        minSdk = 26
        targetSdk = 35
        versionCode = 170
        versionName = "1.7.0-alpha.1"
        buildConfigField("boolean", "VAINAH_CLERK_ENABLED", if (clerkEnabled) "true" else "false")
        buildConfigField("String", "VAINAH_CLERK_PUBLISHABLE_KEY",
            "\""+clerkPublishableKey.replace("\\","").replace("\"","")+"\"")
        buildConfigField("boolean", "VAINAH_LIBBOX_ENABLED", if (nativeLibboxEnabled) "true" else "false")
        buildConfigField("boolean", "VAINAH_XHTTP_ENGINE_ENABLED",
            if (xhttpNativeEnabled) "true" else "false")
        buildConfigField("boolean", "VAINAH_DIRECT_CHECKOUT_ENABLED",
            "false")
    }
    buildFeatures {
        compose = clerkEnabled
        buildConfig = true
    }
    // Clerk's HTTP stack and jspecify both package the same Java 9 OSGi
    // metadata. It is not used by Android and must appear only once in APK.
    packaging {
        resources {
            excludes += "META-INF/versions/9/OSGI-INF/MANIFEST.MF"
        }
    }
    buildTypes {
        getByName("release") { isMinifyEnabled = false }
        getByName("debug") {
            // A test UI APK must never replace the user's working VPN.
            if (isolatedPreview) {
                applicationIdSuffix = ".preview"
                versionNameSuffix = "-preview"
                manifestPlaceholders["vainahAppLabel"] = "VainahVPN"
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    if (nativeLibboxEnabled) {
        sourceSets.getByName("main").java.srcDir("src/libbox/java")
    }
    if (clerkEnabled) {
        sourceSets.getByName("main").java.srcDir("src/clerk/java")
    }
}

// Kotlin 2.4 requires the typed compilerOptions DSL instead of kotlinOptions.
kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    if (clerkEnabled) {
        implementation("com.clerk:clerk-android-ui:1.1.4")
        implementation("com.googlecode.libphonenumber:libphonenumber:9.0.41")
        implementation(platform("androidx.compose:compose-bom:2025.06.01"))
        implementation("androidx.compose.ui:ui")
        implementation("androidx.compose.material3:material3")
        implementation("androidx.activity:activity-compose:1.10.1")
        implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.2")
    }
    // Keep a checkout on screen within our app without collecting card details.
    implementation("androidx.browser:browser:1.8.0")
    // One OS-scheduled HTTPS subscription refresh every ~15 minutes while
    // backgrounded, with network constraints and without a persistent timer.
    implementation("androidx.work:work-runtime:2.10.5")
    // Exactly ONE Go runtime. The bundled native adapter now targets
    // sing-box-lx 1.14.4 specifically. A stock libbox native build is
    // deliberately rejected rather than packaging an incompatible VPN.
    if (nativeLibboxEnabled) {
        require(xhttpNativeEnabled) {
            "Native VainahVPN 1.7 requires -PvainahUseXhttpCore=true " +
                "and the pinned verified XHTTP AAR under android/app/libs/"
        }
        implementation(files("libs/libbox-xhttp-lx.aar"))
    }
    testImplementation("junit:junit:4.13.2")
    // Real org.json implementation for JVM-only configuration contract tests.
    testImplementation("org.json:json:20250517")
}
