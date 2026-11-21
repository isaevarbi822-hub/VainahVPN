package app.vainah.vpn

/**
 * Interprets Android-observed VPN routing metadata, NOT a live DNS-leak test.
 * Never infers "secure", anonymous, egress verified or exit IP correctness.
 *
 * Unknown facts are distinct from missing routes. An absent IPv6 default
 * route can be intentional if IPv6 isn't available, so it is a review item,
 * not evidence of an IP leak.
 */
data class VpnRouteAssessment(
    val code: String,
    val title: String,
    val explanation: String,
    val needsReview: Boolean,
)

object VpnRouteAdvisor {
    fun assess(serviceActive: Boolean, facts: VpnNetworkFacts?): VpnRouteAssessment {
        if (!serviceActive) return VpnRouteAssessment(
            "vpn_off", "VPN не запущен",
            "Для проверки маршрутов сначала подключи Vainah VPN. " +
                "Старые результаты не используются как текущие.",
            false,
        )
        if (facts?.visible == false) return VpnRouteAssessment(
            "vpn_not_visible", "Android не обнаружил VPN-сеть",
            "Служба запущена, но Android сейчас не показывает VPN-сеть. " +
                "Проверь состояние приложения и повтори проверку.",
            true,
        )
        if (facts?.visible != true) return VpnRouteAssessment(
            "vpn_visibility_unknown", "Состояние VPN-маршрутов неизвестно",
            "Android не предоставил достаточно сетевых данных. " +
                "Это не означает утечку или отказ VPN.",
            false,
        )
        if (facts.ipv4DefaultRoute == false ||
            facts.ipv6DefaultRoute == false ||
            facts.dnsConfigured == false
        ) {
            val findings = ArrayList<String>()
            if (facts.ipv4DefaultRoute == false) {
                findings.add("Нет подтверждённого полного маршрута IPv4.")
            }
            if (facts.ipv6DefaultRoute == false) {
                findings.add("Полный маршрут IPv6 не обнаружен; он может не требоваться " +
                    "на сети без IPv6.")
            }
            if (facts.dnsConfigured == false) {
                findings.add("Android не показывает DNS-серверы VPN.")
            }
            return VpnRouteAssessment(
                "vpn_routes_review", "Маршруты требуют проверки",
                findings.joinToString(" ") +
                    " Эти сведения показывают только конфигурацию Android. " +
                    "Реальная доступность сайтов и DNS-утечки не проверялись.",
                true,
            )
        }
        if (facts.ipv4DefaultRoute != true || facts.ipv6DefaultRoute != true ||
            facts.dnsConfigured != true
        ) {
            return VpnRouteAssessment(
                "vpn_routes_incomplete", "Часть данных о маршрутах неизвестна",
                "VPN-сеть обнаружена, но Android не подтвердил все параметры IPv4, " +
                    "IPv6 и DNS. Это не является доказательством утечки.",
                false,
            )
        }
        return VpnRouteAssessment(
            "vpn_routes_present", "Маршруты и DNS обнаружены",
            "Android сообщает о полных маршрутах IPv4 и IPv6 и о настроенном DNS. " +
                "Это НЕ подтверждает, что запросы прошли через VPN: для проверки " +
                "нужен отдельный тест трафика и внешнего IP.",
            false,
        )
    }
}
