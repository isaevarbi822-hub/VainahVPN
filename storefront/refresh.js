/* Progressive motion and an explicit, user-initiated film. No background playback. */
(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!reduced.matches && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        if (document.documentElement.dataset.vxMotion !== 'reduce') {
          entry.target.classList.add('refresh-reveal');
        }
        observer.unobserve(entry.target);
      }
    }, {threshold: 0.08});
    // Content remains visible when JavaScript, observers or animations fail.
    document.querySelectorAll('.refresh-section-heading,.refresh-feature,.refresh-steps article')
      .forEach((node, index) => {
        node.style.setProperty('--reveal-delay', `${(index % 3) * 70}ms`);
        observer.observe(node);
      });
  }
  const video = document.querySelector('[data-intro-video]');
  const desktop = window.matchMedia('(min-width: 901px)');
  desktop.addEventListener('change', event => {
    if (!event.matches) return;
    const menu = document.querySelector('[data-mobile-nav]');
    const toggle = document.querySelector('[data-menu-button]');
    menu?.classList.remove('open');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Открыть меню');
  });
  document.querySelector('[data-play-intro]')?.addEventListener('click', () => {
    if (!video) return;
    // Native controls remain available if loading or playback is refused.
    video.play().catch(() => {});
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && video && !video.paused) video.pause();
  });
})();
