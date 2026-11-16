package app.vainah.vpn

/**
 * Security page claims must not exceed the state observed by VpnService.
 * In particular, STARTING does not mean that a TUN or working VPN exists.
 */
internal object VpnSecurityPresentation {
    data class Status(val title: String, val tone: VainahUi.Tone)

    fun tunnel(phase: String, processRunning: Boolean): Status = when {
        !processRunning -> Status("Служба не запущена", VainahUi.Tone.NEUTRAL)
        phase == VpnConnectionState.STARTING ->
            Status("Подключается", VainahUi.Tone.PURPLE)
        phase == VpnConnectionState.TUN_READY ->
            Status("Туннель создан · трафик не проверен", VainahUi.Tone.PURPLE)
        phase == VpnConnectionState.ONLINE ->
            Status("Туннель запущен · IP не проверен", VainahUi.Tone.PURPLE)
        phase == VpnConnectionState.FAILED ->
            Status("Ошибка подключения", VainahUi.Tone.WARNING)
        else -> Status("Не подключено", VainahUi.Tone.NEUTRAL)
    }
}
