"""Safe public configuration. Credentials must never be returned to the web client."""
import os
import re
from dataclasses import dataclass


def deployment_commit() -> str | None:
    """Expose only Render's validated public commit ID, never arbitrary env text."""
    value = os.environ.get("RENDER_GIT_COMMIT", "")
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


@dataclass(frozen=True)
class Settings:
    mode: str = "preview"
    version: str = "0.1.0"
    project_name: str = "Vainah VPN"

    @classmethod
    def from_env(cls) -> "Settings":
        # Preview is intentional: production APIs must first implement auth and storage.
        raw = os.environ.get("VAINAH_MODE", "preview").strip().lower()
        if raw != "preview":
            raise ValueError("Only VAINAH_MODE=preview is supported until auth is implemented")
        return cls(mode=raw)
