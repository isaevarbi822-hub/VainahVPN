package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Test

class LibboxValidationDetailTest {
    @Test fun recognizesOnlyKnownParserFieldNames() {
        assertEquals("unknown_field_dns_mode",
            LibboxValidationDetail.classify("decode: json: unknown field \"dns_mode\""))
        assertEquals("unknown_field_x_padding_bytes",
            LibboxValidationDetail.classify("decode transport: unrecognized field 'x_padding_bytes'"))
    }

    @Test fun identifiesAnUnsupportedNativeXhttpTransport() {
        assertEquals("unsupported_xhttp",
            LibboxValidationDetail.classify("unknown transport type: xhttp"))
    }

    @Test fun neverExportsHostsTokensOrArbitraryErrorContent() {
        val secret = "vless://00000000-0000-4000-8000-000000000001@private.example:443"
        val code = LibboxValidationDetail.classify("parse failed: $secret")
        assertEquals("native_config_rejected", code)
        assertEquals("unknown", LibboxValidationDetail.safeCode(secret))
        assertEquals("unknown", LibboxValidationDetail.safeCode("unknown_field_private"))
        assertEquals("unknown_field_dns_mode",
            LibboxValidationDetail.safeCode("unknown_field_dns_mode"))
    }
}
