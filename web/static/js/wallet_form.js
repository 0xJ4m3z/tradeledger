// Disables the wallet form's submit button while a fetch is in flight —
// live fetches hit real Polygon RPC + Polymarket API endpoints sequentially
// and can take several seconds, so give visible feedback rather than letting
// the button look inert (or double-submittable) while the page navigates.
(function () {
  const form = document.querySelector('[data-testid="wallet-form"]');
  if (!form) return;

  form.addEventListener('submit', () => {
    const button = form.querySelector('[data-testid="wallet-submit"]');
    if (!button) return;
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.textContent = 'Fetching…';
  });
})();
