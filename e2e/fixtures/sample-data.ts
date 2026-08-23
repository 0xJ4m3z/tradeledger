/**
 * Known-good values derived from sample_data/sample_wallet_positions.json and
 * sample_data/sample_resolved_positions.json, hand-verified against
 * app.services.metrics.compute_dashboard_metrics and app.services.pnl_series
 * (see the numbers checked during Phase 1 smoke-testing).
 *
 * Centralizing them here means tests read as assertions against a documented
 * fixture, not magic numbers, and only need updating in one place if the
 * sample JSON ever changes.
 */
export const SAMPLE = {
  activeCount: 7,
  resolvedCount: 0, // sample_resolved_positions.json seeds Closed, not Resolved — see web/README.md
  closedCount: 10,

  positionsValue: 2256.0,
  walletUsdValue: 0.0,
  totalTrackedValue: 2256.0,

  lossWatchCount: 2, // "S&P 500 Above 5500" and "Tech Sector Layoffs Above 50k" are underwater

  realizedPnlAllTime: 680.5,
  winCount: 6,
  lossCount: 4,

  // Chronologically first/last closed positions (by resolved_date), for chart endpoint assertions.
  firstClosedDate: '2024-07-05',
  lastClosedDate: '2025-04-15',
  // 10 closed positions, each on a distinct date, + the $0 anchor point.
  allTimePnlChartPointCount: 11,
} as const;

export const ACTIVE_POSITION_0 = {
  // Index 0 after sort_by_unrealized_pnl (descending) — see web/data.py.
  market: 'US CPI Below 3.0% — May 2025',
  outcome: 'YES',
  unrealizedPnl: 110.0,
};

export const CLOSED_POSITION_LOSS = {
  // Index 8 after sort_closed_positions_newest_first — a known loss.
  market: 'Bank of England Rate Cut — Aug 2024',
  outcomeHeld: 'NO',
  isWin: false,
};
