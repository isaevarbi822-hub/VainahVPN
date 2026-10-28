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
        val path = System.getenv("VAINAH_SYNTHETIC_CONFIG_OUTPUT")
            ?.takeIf { it.isNotBlank() } ?: return
        val target = java.nio.file.Paths.get(path)
        java.nio.file.Files.createDirectories(target.parent)
        java.nio.file.Files.write(
            target, VlessRealityConfig.profile(safeNode, "192.0.2.25")
                .toByteArray(Charsets.UTF_8)
        )
    }

    @Test fun missingRealityParametersCannotStartTunnel() {
        for (bad in listOf(
            "vless://00000000-0000-4000-8000-000000000001@example.org:443",
            safeNode.replace("security=reality", "security=tls"),
            safeNode.replace("pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "pbk="),
            safeNode.replace("type=tcp", "type=ws")
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                VlessRealityConfig.profile(bad)
            }
        }
    }
}
