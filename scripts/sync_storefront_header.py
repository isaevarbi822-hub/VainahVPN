"""Render the shared navigation into static pages so links work before JS loads."""
from pathlib import Path
import re
import sys

SITE = Path(__file__).resolve().parents[1] / "storefront"
PRIMARY = (
    ("plans.html", "Тарифы"), ("connect.html", "Подключение"),
    ("servers.html", "Серверы"), ("contact.html", "Поддержка"),
)
MORE = (
    ("trial.html", "Пробный период"), ("account.html", "Личный кабинет"),
    ("gifts.html", "Подарочные карты"), ("my-devices.html", "Мои устройства"),
    ("support-center.html", "Мои обращения"), ("tools.html", "Инструменты"),
    ("command-hub.html", "Центр управления"), ("about.html", "О сервисе"),
)
BLOCK = re.compile(r'<header class="vv-header">.*?</header>', re.DOTALL)


def navigation(filename):
    def links(items):
        parts = []
        for path, label in items:
            current = ' aria-current="page"' if filename == path else ""
            parts.append(f'<a href="{path}"{current}>{label}</a>')
        return "\n".join(parts)

    return f'''<header class="vv-header">
  <div class="vv-bar">
    <a href="/" class="vv-brand" aria-label="Vainah VPN — Главная"><span class="vv-mark" aria-hidden="true">V</span><span>Vainah <b>VPN</b></span></a>
    <nav class="vv-primary" aria-label="Основная навигация">{links(PRIMARY)}</nav>
    <div class="vv-actions">
      <a class="vv-account" href="account.html">Кабинет</a>
      <details class="vv-menu"><summary aria-label="Меню сайта"><span class="vv-burger" aria-hidden="true"></span><span>Меню</span></summary>
        <nav class="vv-drawer" aria-label="Все разделы"><div class="vv-drawer-links">{links(PRIMARY + MORE)}</div><div class="vv-menu-tools"></div></nav>
      </details>
    </div>
  </div>
</header>'''


def main():
    changed = []
    for page in sorted(SITE.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        if not BLOCK.search(html):
            continue
        rendered = BLOCK.sub(lambda _: navigation(page.name), html, count=1)
        if rendered != html:
            changed.append(page.name)
            if "--check" not in sys.argv:
                page.write_text(rendered, encoding="utf-8")
    if changed and "--check" in sys.argv:
        raise SystemExit("Navigation out of date: " + ", ".join(changed))


if __name__ == "__main__":
    main()
