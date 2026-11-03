"""Run the complete Vainah VPN storefront on localhost; never a public server."""
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

# Explicitly test-only and localhost. No RollyPay requests or real charges.
os.environ["VAINAH_SHOP_SANDBOX_MODE"] = "mock"
os.environ["VAINAH_SHOP_SANDBOX_ENABLED"] = "enabled"
TOKEN = secrets.token_urlsafe(32)
os.environ["VAINAH_SANDBOX_TEST_TOKEN"] = TOKEN

from uvicorn import run  # noqa: E402
from vainah.main import app  # noqa: E402

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("VAINAH VPN — LOCAL PREVIEW, NO REAL CHARGES")
    print("Website: http://127.0.0.1:8765/")
    print("Tariffs: http://127.0.0.1:8765/plans.html")
    print("Checkout: http://127.0.0.1:8765/checkout.html")
    print("Sandbox token (for checkout test section): " + TOKEN)
    print("Do NOT publish this local token. Press Ctrl+C to stop.")
    print("=" * 62 + "\n", flush=True)
    run(app, host="127.0.0.1", port=8765, log_level="warning")
