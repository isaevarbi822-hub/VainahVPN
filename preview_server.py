"""Run the complete Vainah VPN storefront on localhost; never a public server."""
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

# Default is offline mock. Provider testing is explicit and never enables live checkout.
USE_PROVIDER = sys.argv[1:] == ["--rollypay-sandbox"]
if sys.argv[1:] and not USE_PROVIDER:
    sys.exit("Usage: py -3 preview_server.py [--rollypay-sandbox]")
if USE_PROVIDER and not os.environ.get("ROLLYPAY_API_KEY"):
    sys.exit("Missing ROLLYPAY_API_KEY. Do not paste keys into source files.")
os.environ["VAINAH_SHOP_SANDBOX_MODE"] = "provider" if USE_PROVIDER else "mock"
os.environ["VAINAH_SHOP_SANDBOX_ENABLED"] = "enabled"
os.environ["VAINAH_SHOP_PROVIDER_TEST_ENABLED"] = "enabled" if USE_PROVIDER else "disabled"
TOKEN = secrets.token_urlsafe(32)
os.environ["VAINAH_SANDBOX_TEST_TOKEN"] = TOKEN

from uvicorn import run  # noqa: E402
from vainah.main import app  # noqa: E402

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("VAINAH VPN — ROLLYPAY SANDBOX TEST ONLY" if USE_PROVIDER
          else "VAINAH VPN — LOCAL PREVIEW, NO REAL CHARGES")
    print("Website: http://127.0.0.1:8765/")
    print("Tariffs: http://127.0.0.1:8765/plans.html")
    print("Checkout: http://127.0.0.1:8765/checkout.html")
    print("Mode: " + ("PROVIDER SANDBOX — test:true only" if USE_PROVIDER else "OFFLINE MOCK"))
    print("Sandbox token (for checkout test section): " + TOKEN)
    print("Do NOT publish this local token. Press Ctrl+C to stop.")
    print("=" * 62 + "\n", flush=True)
    run(app, host="127.0.0.1", port=8765, log_level="warning")
