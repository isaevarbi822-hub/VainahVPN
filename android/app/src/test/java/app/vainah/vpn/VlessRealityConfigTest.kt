package app.vainah.vpn

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * Offline contract checks with an invented test node.
 * Never needs H1Cloud credentials and never contacts the internet.
 */
class VlessRealityConfigTest {
    private val safeNode =
        "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
            "?security=reality&type=tcp&sni=example.org&" +
            "pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&fp=chrome&sid=1234"

    @Test fun vpnProfileHasFullDualStackRoutesAndHijackedDNS() {
        val profile = JSONObject(VlessRealityConfig.profile(safeNode, "192.0.2.25"))
        val inbound = profile.getJSONArray("inbounds").getJSONObject(0)
        assertEquals("tun", inbound.getString("type"))
        assertTrue(inbound.getBoolean("auto_route"))
        assertEquals("hijack", inbound.getString("dns_mode"))
        val dnsAddresses = inbound.getJSONArray("dns_address")
        assertEquals(2, dnsAddresses.length())
        assertEquals("172.19.0.2", dnsAddresses.getString(0))
        assertEquals("fd00:19::2", dnsAddresses.getString(1))
        assertEquals(TunDnsFallback.nextAddress("172.19.0.1", 30),
            dnsAddresses.getString(0))
        assertArrayEquals(
            java.net.InetAddress.getByName(TunDnsFallback.nextAddress("fd00:19::1", 126)).address,
            java.net.InetAddress.getByName(dnsAddresses.getString(1)).address)
        val addresses = inbound.getJSONArray("address")
        assertTrue((0 until addresses.length()).any { addresses.getString(it).contains(".") })
        assertTrue((0 until addresses.length()).any { addresses.getString(it).contains(":") })

        val dns = profile.getJSONObject("dns")
        assertEquals("dns-via-vless", dns.getString("final"))
        val servers = dns.getJSONArray("servers")
        val tags = (0 until servers.length()).map { servers.getJSONObject(it).getString("tag") }
        assertTrue(tags.contains("dns-bootstrap"))
        assertTrue(tags.contains("dns-via-vless"))
        val upstream = (0 until servers.length()).map { servers.getJSONObject(it) }
            .first { it.getString("tag") == "dns-via-vless" }
        assertEquals("https", upstream.getString("type"))
        assertEquals("vainah-selected", upstream.getString("detour"))
        assertEquals("vainah-selected", profile.getJSONObject("route").getString("final"))
        assertEquals("dns-bootstrap", profile.getJSONObject("route")
            .getString("default_domain_resolver"))
        val rules = profile.getJSONObject("route").getJSONArray("rules")
        assertEquals(2, rules.length())
        val virtualDnsRule = rules.getJSONObject(0)
        assertEquals("hijack-dns", virtualDnsRule.getString("action"))
        val ips = virtualDnsRule.getJSONArray("ip_cidr")
        assertEquals("172.19.0.2/32", ips.getString(0))
        assertEquals("fd00:19::2/128", ips.getString(1))
        val otherDnsRule = rules.getJSONObject(1)
        assertEquals(53, otherDnsRule.getInt("port"))
        assertEquals("hijack-dns", otherDnsRule.getString("action"))
    }

    @Test fun serverIpPreResolvedAndRealityIdentityRetained() {
        val profile = JSONObject(VlessRealityConfig.profile(safeNode, "192.0.2.25"))
        val outbound = profile.getJSONArray("outbounds").getJSONObject(0)
        assertEquals("192.0.2.25", outbound.getString("server"))
        assertEquals(443, outbound.getInt("server_port"))
        assertEquals("dns-bootstrap", outbound.getString("domain_resolver"))
        assertEquals("00000000-0000-4000-8000-000000000001", outbound.getString("uuid"))
        val tls = outbound.getJSONObject("tls")
        assertTrue(tls.getBoolean("enabled"))
        assertEquals("example.org", tls.getString("server_name"))
        assertTrue(tls.getJSONObject("reality").getBoolean("enabled"))
        assertEquals("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            tls.getJSONObject("reality").getString("public_key"))
    }

    /**
     * GitHub Actions passes a build-directory destination. The resulting file
     * contains ONLY the invented node above; never use a real subscription
     * fixture for executable-core validation or upload it as an artifact.
     */
    @Test fun exportInventedConfigForNativeSingBoxCheck() {
        // Only invented UUID, address, REALITY public key and SNI are exported.
        // Never use a real subscription fixture in GitHub Actions artifacts.
        val legacyFile = System.getenv("VAINAH_SYNTHETIC_CONFIG_OUTPUT")
            ?.takeIf { it.isNotBlank() }
        if (legacyFile != null) {
            val target = java.nio.file.Paths.get(legacyFile)
            java.nio.file.Files.createDirectories(target.parent)
            java.nio.file.Files.write(
                target, VlessRealityConfig.profile(safeNode, "192.0.2.25")
                    .toByteArray(Charsets.UTF_8)
            )
        }
        val dirValue = System.getenv("VAINAH_SYNTHETIC_CONFIG_DIR")
            ?.takeIf { it.isNotBlank() } ?: return
        val dir = java.nio.file.Paths.get(dirValue)
        java.nio.file.Files.createDirectories(dir)
        val realityXhttp = safeNode.replace("type=tcp", "type=xhttp") +
            "&mode=packet-up&path=%2Ftest&x_padding_bytes=100-1000"
        val tlsXhttp = realityXhttp.replace("security=reality", "security=tls")
            .replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "") +
            "&alpn=h2"
        val grpcReality = safeNode.replace("type=tcp", "type=grpc") +
            "&serviceName=test"
        val extraCases = listOf(
            "padding" to JSONObject().put("xPaddingBytes", "400-800"),
            "no-grpc" to JSONObject().put("noGRPCHeader", true),
            "post-bytes" to JSONObject().put("scMaxEachPostBytes", "200000-400000"),
            "post-interval" to JSONObject().put("scMinPostsIntervalMs", "30-60"),
            "xmux" to JSONObject().put("xmux",
                JSONObject().put("max_connections", "3-3")),
            "xmux-xray-camel" to JSONObject().put("xmux",
                JSONObject().put("maxConnections", "3-3")
                    .put("hMaxRequestTimes", "600-900")),
            "session" to JSONObject().put("sessionPlacement", "header")
                .put("sessionKey", "X-Session"),
            "uplink" to JSONObject().put("uplinkHTTPMethod", "POST"),
            "obfs" to JSONObject().put("xPaddingObfsMode", true)
        )
        val examples = listOf(
            "reality-tcp" to safeNode,
            "reality-grpc" to grpcReality,
            "reality-xhttp" to realityXhttp,
            "tls-xhttp" to tlsXhttp
        ) + extraCases.map { (name, value) ->
            "xhttp-$name" to realityXhttp + "&extra=" +
                java.net.URLEncoder.encode(value.toString(), "UTF-8")
        }
        for ((name, node) in examples) {
            java.nio.file.Files.write(
                dir.resolve("$name.json"),
                VlessRealityConfig.profile(node, "192.0.2.25")
                    .toByteArray(Charsets.UTF_8)
            )
        }
    }

    @Test fun grpcAndTlsProduceNativeTransportProfiles() {
        val grpc = safeNode.replace("type=tcp", "type=grpc") +
            "&serviceName=turkey-lte"
        val converted = VlessRealityConfig.outbound(grpc)
        assertEquals("grpc", converted.getJSONObject("transport").getString("type"))
        assertEquals("turkey-lte",
            converted.getJSONObject("transport").getString("service_name"))
        assertTrue(converted.getJSONObject("tls")
            .getJSONObject("reality").getBoolean("enabled"))
        val tlsNode = safeNode.replace("security=reality", "security=tls")
            .replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "")
        val tlsProfile = VlessRealityConfig.outbound(tlsNode)
        assertFalse(tlsProfile.getJSONObject("tls").has("reality"))
        assertTrue(tlsProfile.getJSONObject("tls").getBoolean("enabled"))
        assertEquals("example.org", tlsProfile.getJSONObject("tls").getString("server_name"))
    }

    @Test fun nativeXhttpTlsAndRealityProfilesPreserveWireParameters() {
        val tls = safeNode.replace("security=reality", "security=tls")
            .replace("type=tcp", "type=xhttp")
            .replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "")
            .plus("&path=%2Ftr%2Flte&host=turkey.example.org&mode=packet-up")
        val tlsOutbound = VlessRealityConfig.outbound(tls)
        assertFalse(tlsOutbound.getJSONObject("tls").has("reality"))
        val xhttp = tlsOutbound.getJSONObject("transport")
        assertEquals("xhttp", xhttp.getString("type"))
        assertEquals("/tr/lte", xhttp.getString("path"))
        assertEquals("packet-up", xhttp.getString("mode"))
        assertEquals("turkey.example.org", xhttp.getString("host"))
        assertEquals("example.org", tlsOutbound.getJSONObject("tls").getString("server_name"))

        val reality = safeNode.replace("type=tcp", "type=xhttp") +
            "&path=%2Fhidden&mode=auto&x_padding_bytes=100-1000"
        val realityOutbound = VlessRealityConfig.outbound(reality)
        assertEquals("xhttp", realityOutbound.getJSONObject("transport").getString("type"))
        assertEquals("auto", realityOutbound.getJSONObject("transport").getString("mode"))
        assertEquals("100-1000", realityOutbound.getJSONObject("transport")
            .getString("x_padding_bytes"))
        assertTrue(realityOutbound.getJSONObject("tls").getJSONObject("reality")
            .getBoolean("enabled"))
        assertEquals("xhttp", VlessRealityConfig.outbound(
            reality.replace("type=xhttp", "type=splithttp")
        ).getJSONObject("transport").getString("type"))
    }

    @Test fun invalidXhttpModesAndFlowCannotStartTunnel() {
        val xhttp = safeNode.replace("type=tcp", "type=xhttp")
        for (bad in listOf(
            xhttp + "&mode=invalid",
            xhttp + "&path=%0A",
            xhttp + "&x_padding_bytes=not-number",
            xhttp + "&flow=xtls-rprx-vision"
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                VlessRealityConfig.outbound(bad)
            }
        }
    }

    @Test fun explicitHappAlpnIsPreservedForNativeHandshake() {
        val outbound = VlessRealityConfig.outbound(
            safeNode + "&alpn=h2%2Chttp%2F1.1")
        val alpn = outbound.getJSONObject("tls").getJSONArray("alpn")
        assertEquals(listOf("h2", "http/1.1"),
            (0 until alpn.length()).map { alpn.getString(it) })
        assertFalse(VlessRealityConfig.outbound(safeNode)
            .getJSONObject("tls").has("alpn"))

        for (bad in listOf("&alpn=%0A", "&alpn=h2%2C", "&alpn=h2%0Dfake")) {
            assertThrows(IllegalArgumentException::class.java) {
                VlessRealityConfig.outbound(safeNode + bad)
            }
        }
    }

    @Test fun mixedCaseXhttpTlsQueryMatchesServerListInspection() {
        val tls = safeNode.replace("security=reality", "SeCuRiTy=TLS")
            .replace("type=tcp", "TYPE=XHTTP")
            .replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "")
            .replace("&fp=chrome", "&FP=chrome") +
            "&PATH=%2Ftr%2Fip&MODE=packet-up&ALPN=h2"
        val outbound = VlessRealityConfig.outbound(tls)
        assertEquals("xhttp", outbound.getJSONObject("transport").getString("type"))
        assertEquals("/tr/ip", outbound.getJSONObject("transport").getString("path"))
        assertEquals("packet-up", outbound.getJSONObject("transport").getString("mode"))
        assertEquals("h2", outbound.getJSONObject("tls").getJSONArray("alpn").getString(0))
        assertFalse(outbound.getJSONObject("tls").has("reality"))
        assertEquals(
            BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED,
            SubscriptionNodeSupport.inspect(tls)?.connectable)
    }

    @Test fun conflictingCaseInsensitiveProtocolKeysAreRejected() {
        val ambiguous = safeNode + "&SECURITY=tls"
        assertThrows(IllegalArgumentException::class.java) {
            VlessRealityConfig.outbound(ambiguous)
        }
    }

    @Test fun missingRealityParametersCannotStartTunnel() {
        for (bad in listOf(
            "vless://00000000-0000-4000-8000-000000000001@example.org:443",
            safeNode.replace("security=reality", "security=none"),
            safeNode.replace("pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "pbk="),
            safeNode.replace("type=tcp", "type=ws")
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                VlessRealityConfig.profile(bad)
            }
        }
    }
}
