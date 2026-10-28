import base64

import pytest

from vainah.inspector import InvalidSubscription, inspect_subscription

VALID = "vless://11111111-1111-4111-8111-111111111111@de.example.com:443?security=reality&sni=de.example.com&pbk=pubkey#Germany"


def test_vless_reality_inspected_without_uuid_leak():
    result = inspect_subscription(VALID)
    assert result["node_count"] == 1
    assert result["nodes"][0]["security"] == "reality"
    assert "11111111-" not in str(result)


def test_base64_subscription():
    token = base64.b64encode((VALID + "\n" + VALID).encode()).decode()
    assert inspect_subscription(token)["node_count"] == 2


@pytest.mark.parametrize("raw", [
    "", "not a subscription", "vless://oops@server.example:443?security=reality",
    "http://example.com/list", "https://localhost/key",
    "https://127.0.0.1/list", "vless://nope@server.example:443",
])
def test_invalid_input(raw):
    with pytest.raises(InvalidSubscription):
        inspect_subscription(raw)


def test_https_link_not_fetched():
    result = inspect_subscription("https://vpn.example.com/api/subscription?token=private")
    assert result["kind"] == "remote_url"
    assert result["nodes"] == []
    assert "private" not in str(result)
