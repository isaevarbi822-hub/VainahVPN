"""Catch broken internal links and missing browser assets before publishing.

Covers all static storefront HTML pages without making network requests.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parents[2] / "storefront"
CHECK_EXTENSIONS = {".html", ".css", ".js", ".svg", ".png", ".webp", ".jpg", ".jpeg"}


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for attribute in ("href", "src"):
            if attribute in values and values[attribute]:
                self.links.append((attribute, values[attribute]))


def test_every_static_storefront_page_resolves_local_assets_and_links():
    errors: list[str] = []
    for page in sorted(SITE.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        parser = AssetLinks()
        parser.feed(html)
        for _kind, raw in parser.links:
            split = urlsplit(raw)
            if split.scheme or split.netloc or raw.startswith("//"):
                continue
            route = unquote(split.path)
            if not route or route.endswith("/"):
                continue
            route = route.lstrip("/")
            suffix = Path(route).suffix.lower()
            if suffix not in CHECK_EXTENSIONS:
                continue
            destination = (SITE / route).resolve()
            if not destination.is_relative_to(SITE.resolve()):
                errors.append(f"{page.name}: unsafe path {raw}")
            elif not destination.is_file():
                errors.append(f"{page.name}: missing {raw}")
    assert not errors, "\n".join(errors[:80])
