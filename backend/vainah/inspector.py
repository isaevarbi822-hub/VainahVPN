"""Offline, read-only subscription inspection. Never fetch arbitrary user URLs."""
import base64
import binascii
import ipaddress
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

MAX_NODES = 64


class InvalidSubscription(ValueError):
    pass


def _unpack_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise InvalidSubscription("Введите VLESS-ключ или текст подписки.")
    if value.startswith(("vless://", "https://", "http://")) or "\n" in value:
        return value
    try:
        compact = "".join(value.split())
        if len(compact) % 4 == 1:
            raise InvalidSubscription("Неверный формат Base64-подписки.")
        decoded = base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_", validate=True)
        text = decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidSubscription("Ожидается VLESS-ключ, HTTPS-ссылка или Base64-подписка.") from exc
    if not text.strip():
        raise InvalidSubscription("Подписка пуста.")
    return text


def _inspect_vless(uri: str) -> dict:
    try:
        u = urlsplit(uri)
        if u.scheme.lower() != "vless" or not u.username or not u.hostname:
            raise ValueError("Missing VLESS fields")
        UUID(unquote(u.username))
        port = u.port
        if port is None or not (1 <= port <= 65535):
            raise ValueError("Invalid port")
        host = u.hostname
        # Validate syntactic shape, not network availability.
        if len(host) > 253 or any(c.isspace() for c in host):
            raise ValueError("Invalid host")
        q = parse_qs(u.query, keep_blank_values=True)
        security = (q.get("security") or ["none"])[0].lower()
        if security not in {"none", "tls", "reality"}:
            raise ValueError("Unsupported security")
        if security == "reality" and (not q.get("pbk") or not q.get("sni")):
            raise ValueError("REALITY requires pbk and sni")
        label = unquote(u.fragment).strip()[:64] or f"VLESS · {host}"
        return {"label": label, "protocol": "vless", "security": security, "host": host, "port": port}
    except (ValueError, TypeError) as exc:
        raise InvalidSubscription("Некорректный VLESS-ключ: проверьте UUID, адрес, порт и REALITY.") from exc


def inspect_subscription(raw: str) -> dict:
    value = _unpack_text(raw)
    # Remote URLs are recognized, never fetched from the API (SSRF protection).
    if value.startswith(("https://", "http://")) and "\n" not in value:
        try:
            u = urlsplit(value)
        except ValueError as exc:
            raise InvalidSubscription("Некорректная HTTPS-ссылка подписки.") from exc
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
            raise InvalidSubscription("Ссылка подписки должна быть HTTPS без логина и фрагмента.")
        try:
            addr = ipaddress.ip_address(u.hostname)
            if not addr.is_global:
                raise InvalidSubscription("Локальные адреса не принимаются.")
        except ValueError as exc:
            if isinstance(exc, InvalidSubscription):
                raise
        if u.hostname.lower() in {"localhost"} or u.hostname.lower().endswith((".local", ".internal")):
            raise InvalidSubscription("Локальные адреса не принимаются.")
        return {
            "kind": "remote_url", "nodes": [], "node_count": 0,
            "message": "HTTPS-ссылка распознана. Загрузка с сервера здесь отключена.",
        }

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) > MAX_NODES:
        raise InvalidSubscription(f"Допускается не более {MAX_NODES} узлов за раз.")
    if not lines or any(not line.startswith("vless://") for line in lines):
        raise InvalidSubscription("В этой версии поддерживается только VLESS-текст.")
    nodes = [_inspect_vless(line) for line in lines]
    return {
        "kind": "vless_text", "nodes": nodes, "node_count": len(nodes),
        "message": "Формат проверен локально. Работу туннеля это не подтверждает.",
    }
