// Auto-refresh every 5 minutes when a live wallet is loaded — mirrors the
// desktop app's "Auto-refresh every 5 min" checkbox (on by default since
// v0.3.2), including remembering the user's on/off choice.
//
// Unlike the manual "Refresh" button (a plain form submit that navigates to
// "/" so the user sees the flash-message confirmation), this refreshes via
// fetch() + reloads the CURRENT page — so auto-refresh never yanks you away
// from whatever page/range you're looking at.
(function () {
  const STORAGE_KEY = 'tl_autorefresh';
  const INTERVAL_MS = 5 * 60 * 1000;

  const checkbox = document.getElementById('auto-refresh-checkbox');
  if (!checkbox) return; // sample mode — nothing to auto-refresh yet

  checkbox.checked = localStorage.getItem(STORAGE_KEY) !== 'off';

  let timer = null;

  function doRefresh() {
    fetch('/wallet/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'address=', // blank → server reuses the currently-loaded wallet
    })
      .then(() => window.location.reload())
      .catch(() => {
        // Silent — don't interrupt the user over a failed background
        // refresh; the "Last updated" time simply stays stale until the
        // next attempt (or a manual Refresh) succeeds.
      });
  }

  function start() {
    stop();
    timer = setInterval(doRefresh, INTERVAL_MS);
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  checkbox.addEventListener('change', () => {
    localStorage.setItem(STORAGE_KEY, checkbox.checked ? 'on' : 'off');
    if (checkbox.checked) {
      start();
    } else {
      stop();
    }
  });

  if (checkbox.checked) start();
})();
