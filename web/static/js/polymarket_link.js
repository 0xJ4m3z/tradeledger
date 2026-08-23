// Right-click (and Ctrl/Cmd+click) on any position row or the position
// detail page opens that market's Polymarket page in a new tab — mirrors
// the desktop app's right-click context menu / Ctrl+click convention across
// every QTableWidget-based table (app/ui/polymarket_menu.py).
//
// The target URL is rendered server-side into each element's
// [data-polymarket-url] attribute via app.services.polymarket_links —
// there's no URL-building logic here, just reading what the server already
// computed, so there's nothing to keep in sync if that logic ever changes.
(function () {
  let menuEl = null;

  function closeMenu() {
    if (menuEl) {
      menuEl.remove();
      menuEl = null;
    }
  }

  function openInNewTab(url) {
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  function showContextMenu(x, y, url) {
    closeMenu();
    menuEl = document.createElement('div');
    menuEl.className = 'context-menu';
    menuEl.setAttribute('data-testid', 'polymarket-context-menu');
    menuEl.style.left = `${x}px`;
    menuEl.style.top = `${y}px`;

    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'context-menu-item';
    item.setAttribute('data-testid', 'open-on-polymarket');

    if (url) {
      item.textContent = 'Open on Polymarket ↗';
      item.addEventListener('click', () => {
        openInNewTab(url);
        closeMenu();
      });
    } else {
      item.textContent = 'No Polymarket link available';
      item.disabled = true;
      item.classList.add('context-menu-item-disabled');
    }

    menuEl.appendChild(item);
    document.body.appendChild(menuEl);

    // Keep the menu on-screen if it would overflow the right/bottom edge.
    const rect = menuEl.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      menuEl.style.left = `${x - rect.width}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menuEl.style.top = `${y - rect.height}px`;
    }
  }

  document.addEventListener('contextmenu', (evt) => {
    const target = evt.target.closest('[data-polymarket-url]');
    if (!target) return;
    evt.preventDefault();
    showContextMenu(evt.pageX, evt.pageY, target.dataset.polymarketUrl || null);
  });

  // Ctrl/Cmd+click as a one-step alternative to right-click → menu → click.
  // Only intercepts when a link is actually available, so a plain click (or
  // a Ctrl+click with no Polymarket link) still falls through to normal
  // in-app navigation.
  document.addEventListener('click', (evt) => {
    if (menuEl && !menuEl.contains(evt.target)) {
      closeMenu();
    }

    if (!(evt.ctrlKey || evt.metaKey)) return;
    const target = evt.target.closest('[data-polymarket-url]');
    if (!target || !target.dataset.polymarketUrl) return;
    evt.preventDefault();
    evt.stopPropagation();
    openInNewTab(target.dataset.polymarketUrl);
  });

  document.addEventListener('keydown', (evt) => {
    if (evt.key === 'Escape') closeMenu();
  });
})();
