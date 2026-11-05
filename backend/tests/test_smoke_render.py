"""The public Render smoke checker never performs live payment operations."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def load_checker():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "smoke_render.py"
    spec = importlib.util.spec_from_file_location("smoke_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("sandbox_available", [False, True])
@pytest.mark.parametrize("revision, expected_revision, result", [
    (None, None, 0),
    ("a" * 40, "a" * 40, 0),
    ("a" * 40, "b" * 40, 1),
    (None, "a" * 40, 1),
])
def test_smoke_checks_expected_public_contract(
    monkeypatch, sandbox_available, revision, expected_revision, result,
):
    checker = load_checker()
    def fake_fetch(_base, path, *, method="GET", payload=None):
        responses = {
            "/": (200, {}),
            "/checkout.html": (200, {}),
            "/app": (200, {}),
            "/api/health": (200, {"ok": True, "commit_sha": revision}),
            "/api/shop/plans": (200, {
                "currency": "RUB",
                "items": [{"id": i} for i in
                          ["30", "60", "90", "180", "365", "365-family"]],
            }),
            "/api/shop/config": (200, {
                "checkout_ready": False, "sandbox_available": sandbox_available,
            }),
            "/api/site/services": (200, {
                "services": {"database": {"status": "ok"}},
            }),
            "/api/shop/sandbox/orders": (401, {}),
            "/api/v1/security": (200, {
                "payments_enabled": False, "native_tunnel_attached": False,
            }),
            "/api/shop/checkout": (503, {}),
        }
        if path == "/api/shop/checkout":
            assert method == "POST"
            assert payload == {"plan": "30"}
        else:
            assert method == "GET"
        status, response = responses[path]
        return status, json.dumps(response).encode()

    monkeypatch.setattr(checker, "fetch", fake_fetch)
    argv = ["smoke_render.py"]
    if expected_revision:
        argv += ["--expected-commit", expected_revision]
    monkeypatch.setattr(sys, "argv", argv)
    assert checker.main() == result


def test_smoke_rejects_invalid_expected_revision_before_any_request(monkeypatch):
    checker = load_checker()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid arguments must not trigger requests")

    monkeypatch.setattr(checker, "fetch", forbidden)
    monkeypatch.setattr(sys, "argv", ["smoke_render.py", "--expected-commit", "bad"])
    with pytest.raises(SystemExit) as error:
        checker.main()
    assert error.value.code == 2


@pytest.mark.parametrize("config", [None, ["PRIVATE_REMOTE_BODY"], {"checkout_ready": "false"}])
def test_smoke_reports_malformed_public_data_without_echo(monkeypatch, capsys, config):
    checker = load_checker()

    def malformed(_base, path, **_kwargs):
        assert path != "/api/shop/checkout"
        body = {"items": ["PRIVATE_REMOTE_BODY"] * 6, "currency": "RUB"}
        if path == "/api/site/services":
            body = {"services": None}
        if path == "/api/shop/config":
            body = config
        return 200, json.dumps(body).encode()

    monkeypatch.setattr(checker, "fetch", malformed)
    monkeypatch.setattr(sys, "argv", ["smoke_render.py"])
    assert checker.main() == 1
    assert "PRIVATE_REMOTE_BODY" not in capsys.readouterr().out


def test_smoke_refuses_checkout_when_public_payments_enabled(monkeypatch):
    checker = load_checker()
    seen = []
    def fake_fetch(_base, path, *, method="GET", payload=None):
        seen.append(path)
        assert path != "/api/shop/checkout"
        responses = {
            "/api/health": {"ok": True},
            "/api/shop/plans": {"currency": "RUB", "items": [
                {"id": i} for i in
                ["30", "60", "90", "180", "365", "365-family"]]},
            "/api/shop/config": {
                "checkout_ready": True, "sandbox_available": False},
            "/api/site/services": {
                "services": {"database": {"status": "ok"}}},
            "/api/v1/security": {
                "payments_enabled": False, "native_tunnel_attached": False},
        }
        return (401 if path == "/api/shop/sandbox/orders" else 200,
                json.dumps(responses.get(path, {})).encode())

    monkeypatch.setattr(checker, "fetch", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["smoke_render.py"])
    assert checker.main() == 1
    assert "/api/shop/checkout" not in seen
