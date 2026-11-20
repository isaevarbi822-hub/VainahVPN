(() => {
  const menu = document.querySelector('.vv-menu');
  if (!menu) return;
  const summary = menu.querySelector('summary');
  window.matchMedia?.('(max-width: 860px)').addEventListener?.('change', () => {
    if (menu.open) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open && !document.querySelector('dialog[open]')) {
      menu.open = false;
      summary.focus();
    }
  });
  document.addEventListener('click', event => {
    if (menu.open && (!menu.contains(event.target) || event.target.closest('a'))) menu.open = false;
  });
})();
