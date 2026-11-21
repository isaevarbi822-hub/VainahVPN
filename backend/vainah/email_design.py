"""Shared, mobile-friendly transactional email design for Vainah VPN.

The body is trusted HTML assembled by our server, never user-supplied HTML.
No remote fonts, trackers, external scripts, or credentials are used.
"""
from __future__ import annotations

import html
import os
import re
from email.utils import parseaddr
from html.parser import HTMLParser

ACCOUNT_URL = "https://vainahvpn-python-preview.onrender.com/account.html"
PUBLIC_SITE = "https://vainahvpn.onrender.com"
BRAND_IMAGE = PUBLIC_SITE + "/email-avatar.png"
DEFAULT_SENDER_NAME = "Vainah VPN"
SAFE_SENDER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,49}\Z")
SAFE_ADDRESS = re.compile(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+\Z")


def sender_identity(raw: str) -> str:
    """Keep the *verified* sending mailbox; improve only its visible label."""
    _, address = parseaddr(raw)
    if not SAFE_ADDRESS.fullmatch(address) or "\r" in raw or "\n" in raw:
        raise ValueError("EMAIL_SENDER_ADDRESS_INVALID")
    name = os.environ.get("VAINAH_EMAIL_SENDER_NAME", DEFAULT_SENDER_NAME)
    name = name.strip()
    if not SAFE_SENDER_NAME.fullmatch(name):
        name = DEFAULT_SENDER_NAME
    return f"{name} <{address}>"


def reply_to_identity() -> str | None:
    """Optional response mailbox, configured only after provider verification."""
    value = os.environ.get("VAINAH_EMAIL_REPLY_TO", "").strip()
    if not value:
        return None
    _, address = parseaddr(value)
    if (
        not SAFE_ADDRESS.fullmatch(address)
        or "\r" in value
        or "\n" in value
    ):
        raise ValueError("EMAIL_REPLY_TO_INVALID")
    return address


def _classification(subject: str) -> tuple[str, str, str]:
    lower = subject.casefold()
    if "тестов" in lower:
        return ("ТЕСТОВОЕ ПИСЬМО", "Проверка доставки", "Это тестовое уведомление. Настоящих списаний оно не подтверждает.")
    if "код" in lower or "подтвержден" in lower or "вход" in lower:
        return ("БЕЗОПАСНОСТЬ", "Проверка электронной почты", "Не сообщай одноразовый код никому, даже службе поддержки.")
    if "поддержк" in lower or "обращен" in lower:
        return ("ПОДДЕРЖКА", "Ответ службы поддержки", "Новое сообщение по твоему обращению.")
    if "напоминан" in lower or "продлен" in lower or "истеч" in lower:
        return ("НАПОМИНАНИЕ", "Время проверить подписку", "Проверь срок доступа к VPN.")
    if "подписк" in lower or "оплат" in lower or "квитанц" in lower or "доступ" in lower:
        return ("ПОДПИСКА", "Обновление VPN-доступа", "Информация о твоей подписке.")
    return ("УВЕДОМЛЕНИЕ", "Новости твоего аккаунта", "Сообщение от Vainah VPN.")


class _TextFromHtml(HTMLParser):
    """Plain text alternative for mail clients with disabled HTML rendering."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "h1", "h2", "h3", "div", "li", "br", "tr"}:
            self.parts.append("\n")
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.links:
            link = self.links.pop()
            if link and link.startswith("https://"):
                # If the anchor already prints the URL, don't repeat it.
                line = "".join(self.parts).split("\n")[-1]
                if link not in html.unescape(line):
                    self.parts.append(" (" + html.unescape(link) + ")")
        if tag in {"p", "h1", "h2", "h3", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plaintext_version(body: str) -> str:
    parser = _TextFromHtml()
    parser.feed(body)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "Vainah VPN\n\n" + "\n".join(x for x in lines if x) + "\n\n" + ACCOUNT_URL


def render_email(subject: str, body: str) -> str:
    """Table-based email HTML with inline CSS for Outlook, Gmail and phones."""
    label, heading, preheader = _classification(subject)
    label = html.escape(label)
    heading = html.escape(heading)
    preheader = html.escape(preheader)
    # Keep real provider URLs / subscriptions only in the trusted message body.
    return (
        '<!doctype html><html lang="ru"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<title>' + html.escape(subject) + '</title>'
        '</head><body style="margin:0;padding:0;background:#080e20;'
        'font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">'
        '<div style="display:none!important;font-size:1px;color:#080e20;'
        'line-height:1px;max-height:0;max-width:0;opacity:0;'
        'overflow:hidden;mso-hide:all">' + preheader + '</div>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="background:#080e20;border-collapse:collapse">'
        '<tr><td align="center" style="padding:28px 12px 36px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="width:100%;max-width:580px;border-collapse:separate;'
        'border-spacing:0">'
        '<tr><td style="padding:24px 27px;background:#151f42;'
        'border-radius:18px 18px 0 0">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td style="padding-right:14px;vertical-align:middle">'
        '<img src="' + BRAND_IMAGE + '" width="58" height="58" '
        'alt="Vainah VPN" style="display:block;border:0;border-radius:50%;'
        'width:58px;height:58px;background:#111b37"></td>'
        '<td style="vertical-align:middle">'
        '<span style="color:#ffffff;font-size:21px;letter-spacing:.4px;'
        'font-weight:800">VAINAH <span style="color:#a9b8ff">VPN</span></span>'
        '<div style="color:#b8c5e8;font-size:12px;line-height:1.5;'
        'padding-top:4px">Твоё соединение. Твои правила.</div>'
        '</td></tr></table></td></tr>'
        '<tr><td style="background:#ffffff;padding:29px 28px 30px;'
        'border-radius:0 0 18px 18px">'
        '<p style="margin:0 0 10px;font-size:11px;font-weight:800;'
        'letter-spacing:1.3px;color:#665bd3">' + label + '</p>'
        '<h1 style="font-family:Arial,Helvetica,sans-serif;font-size:25px;'
        'line-height:1.25;letter-spacing:-.5px;color:#111a36;'
        'margin:0 0 22px">' + heading + '</h1>'
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
        'line-height:1.7;color:#24314b;overflow-wrap:anywhere;'
        'word-break:break-word">' + body + '</div>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:25px 0 10px"><tr><td bgcolor="#403dd3" '
        'style="border-radius:11px">'
        '<a href="' + ACCOUNT_URL + '" '
        'style="display:inline-block;background:#403dd3;border-radius:11px;'
        'color:#ffffff;text-decoration:none;font-size:14px;'
        'font-weight:700;line-height:20px;padding:14px 22px">'
        'Открыть личный кабинет</a></td></tr></table>'
        '<p style="color:#68748d;font-size:12px;line-height:1.6;'
        'margin:22px 0 0">Если письмо пришло неожиданно, не переходи '
        'по незнакомым ссылкам и не передавай никому коды или VPN-ключи.</p>'
        '</td></tr>'
        '<tr><td align="center" style="padding:20px 10px 4px;'
        'color:#abb9d6;font-size:12px;line-height:1.65">'
        '© Vainah VPN · Автоматическое уведомление'
        '<br><a href="' + PUBLIC_SITE + '" style="color:#bdb8ff;'
        'text-decoration:none">vainahvpn.onrender.com</a>'
        '<br>Это письмо предназначено только получателю.'
        '</td></tr></table></td></tr></table></body></html>'
    )
