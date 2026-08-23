// Client-side market-name filter for position list tables.
// Pure DOM show/hide — no framework, easy to assert against in Playwright
// via the [hidden] attribute and the #result-count text.
(function () {
  const input = document.getElementById("position-filter");
  const table = document.getElementById("positions-table");
  if (!input || !table) return;

  const countEl = document.querySelector('[data-testid="result-count"]');
  const rows = Array.from(table.querySelectorAll('tbody tr[data-testid="position-row"]'));

  function apply() {
    const q = input.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      const match = !q || (row.dataset.market || "").includes(q);
      row.hidden = !match;
      if (match) visible += 1;
    });
    if (countEl) {
      countEl.textContent = `${visible} position${visible !== 1 ? "s" : ""}`;
    }
  }

  input.addEventListener("input", apply);
})();
