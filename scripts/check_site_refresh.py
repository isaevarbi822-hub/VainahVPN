"""Optional real-browser regression: run against the local preview server.

Requires Playwright and a local Chromium; no live provider operations are made.
Run: python scripts/check_site_refresh.py
"""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright


def main():
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("BROWSER_EXECUTABLE", "/usr/bin/chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8000/plans.html", wait_until="networkidle")
        page.wait_for_selector(".tariff-card")
        assert page.locator(".tariff-card").count() == 75
        for width in [320, 375, 390, 600, 768, 1024, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 950})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            for card in page.locator(".tariff-card:visible").all():
                box = card.bounding_box()
                assert 0 <= box["x"] and box["x"] + box["width"] <= width + 1, width
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator('[data-tariff-search]').fill("четыре недели")
        assert page.locator('.tariff-card:visible').count() == 2
        for button in page.locator('.tariff-card:visible .tariff-compare-toggle').all():
            button.click()
        assert page.locator('[data-tariff-compare-items] article').count() == 2
        page.locator('[data-tariff-compare-clear]').click()
        assert page.locator('[data-tariff-compare]').is_hidden()
        page.locator('[data-tariff-reset]').click()
        page.locator('[data-tariff-filter="family"]').click()
        assert page.locator('.tariff-card:visible').count() == 12
        page.locator('[data-tariff-more]').click()
        assert page.locator('.tariff-card:visible').count() == 24
        page.locator('[data-tariff-sort]').select_option("price")
        assert page.locator('.tariff-card:visible .btn-primary').first.get_attribute('href') == '/checkout.html?plan=family-3d'
        page.locator('[data-tariff-devices]').select_option("3")
        assert page.locator('[data-tariff-empty]').is_visible()
        page.locator('[data-tariff-reset]').click()
        assert page.locator('.tariff-card:visible').count() == 12
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        for width in [320, 375, 390, 600, 768, 1024, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 950})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.set_viewport_size({"width": 390, "height": 844})
        menu = page.locator('[data-menu-button]')
        menu.click()
        assert menu.get_attribute('aria-expanded') == 'true'
        assert page.locator('[data-mobile-nav]').is_visible()
        # Rotation / resizing must not leave the mobile navigation open on desktop.
        page.set_viewport_size({'width': 1024, 'height': 844})
        assert menu.get_attribute('aria-expanded') == 'false'
        assert page.locator('[data-mobile-nav]').is_hidden()
        page.set_viewport_size({'width': 390, 'height': 844})
        menu.click()
        menu.click()
        assert menu.get_attribute('aria-expanded') == 'false'
        page.get_by_role('button', name='Настроить оформление Vainah VPN').click()
        preferences = page.locator('dialog.vx-ultra-dialog')
        assert preferences.is_visible()
        preferences.get_by_label('Уменьшить анимации и эффекты').check()
        assert page.locator('.refresh-globe').evaluate('(e) => getComputedStyle(e).animationName') == 'none'
        preferences.get_by_role('button', name='Вернуть настройки по умолчанию').click()
        preferences.get_by_role('button', name='Закрыть настройки').click()
        page.locator('.refresh-more [data-vx-open-search]').click()
        finder = page.locator('dialog.vx-finder')
        assert finder.is_visible()
        finder.get_by_role('searchbox').fill('тарифы')
        assert finder.locator('a[href="plans.html"]').is_visible()
        finder.get_by_role('button', name='Закрыть', exact=True).click()
        page.locator('[data-play-intro]').click()
        page.wait_for_function("() => document.querySelector('video').currentTime > 0.2")
        assert page.locator('video').evaluate('(v) => v.duration') == 30
        page.locator('video').evaluate('(v) => {v.playbackRate = 8;}')
        page.wait_for_function("() => document.querySelector('video').ended")
        assert page.locator('video').evaluate('(v) => v.error') is None
        # Decode the shipped AAC, rather than checking only that an audio stream exists.
        audio = page.evaluate("""async () => {
          const response = await fetch(document.querySelector('video').currentSrc);
          const context = new OfflineAudioContext(2, 48000, 48000);
          const buffer = await context.decodeAudioData(await response.arrayBuffer());
          const samples = buffer.getChannelData(0);
          let peak = 0, energy = 0, lead = 0;
          for (let i = 0; i < samples.length; i++) {
            peak = Math.max(peak, Math.abs(samples[i]));
            energy += samples[i] ** 2;
            if (i < buffer.sampleRate / 4) lead = Math.max(lead, Math.abs(samples[i]));
          }
          return {duration: buffer.duration, channels: buffer.numberOfChannels,
            peak, rms: Math.sqrt(energy / samples.length), lead};
        }""")
        assert abs(audio['duration'] - 30) < .05, audio
        assert audio['channels'] == 2, audio
        assert .01 < audio['rms'] and audio['peak'] < .99, audio
        assert audio['lead'] < .001, audio
        page.emulate_media(reduced_motion="reduce")
        assert page.locator('.refresh-globe').evaluate('(e) => getComputedStyle(e).animationName') == 'none'
        assert not errors, errors
        browser.close()
    print("PASS: responsive layouts, 75 tariffs, search, filters, menu, 30s video, decoded stereo audio, reduced motion")


if __name__ == "__main__":
    main()
