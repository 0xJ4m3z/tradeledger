"""Polymarket public market WebSocket stream.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market and subscribes
to one or more CLOB token IDs.  Emits Qt signals for price updates, trade events,
and market resolutions — no authentication required.

Protocol details:
  - Send {"assets_ids": [...], "type": "market", "custom_feature_enabled": true} to subscribe.
  - Send the text frame "PING" every 10 s; server replies with "PONG".
  - Reconnects automatically after any disconnect (5 s delay).
"""
from __future__ import annotations

import json
import threading
import time
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

_WS_URL          = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
_PING_INTERVAL_S = 10   # seconds — Polymarket requires app-level PING text frames
_RECONNECT_DELAY = 5    # seconds between reconnect attempts
_PRICE_MIN_GAP_S = 0.5  # per-asset cap on price_updated emits (busy books send ~250 msg/s)


def _book_mid(pc: dict) -> Optional[float]:
    """Midpoint of a price_change entry's best bid/ask, or None if absent.

    pc["price"] is the price *level* whose resting size changed — any level
    in the book, e.g. a 0.01 bid — not the market price, so it is never used.
    """
    try:
        bid = float(pc.get("best_bid") or 0)
        ask = float(pc.get("best_ask") or 0)
    except (TypeError, ValueError):
        return None
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return None


class MarketStreamThread(QThread):
    """Subscribe to Polymarket's public market WebSocket for one or more CLOB token IDs.

    Signals (all safe to connect to main-thread slots):
      price_updated(asset_id, price)     — a last_trade_price or price_change event arrived
      trade_occurred(asset_id, side)     — a trade happened on one of our tokens (BUY/SELL)
      market_resolved(asset_id, winner)  — market resolved; winner = winning outcome string
      stream_connected()                 — WebSocket successfully (re)connected
      stream_disconnected()              — connection closed; will reconnect shortly
    """

    price_updated      = Signal(str, float)  # (asset_id, price)
    trade_occurred     = Signal(str, str)    # (asset_id, side)
    market_resolved    = Signal(str, str)    # (asset_id, winning_outcome)
    stream_connected   = Signal()
    stream_disconnected = Signal()

    def __init__(self, token_ids: List[str], parent=None):
        super().__init__(parent)
        self._token_ids = list(filter(None, token_ids))
        self._stop_flag = False
        self._ws        = None
        self._last_emit: dict = {}   # asset_id -> (monotonic time, price)
        self._last_parse      = 0.0  # monotonic time of the last parsed book/price message

    # ── Public ────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the thread to stop, close the socket, and do not reconnect."""
        self._stop_flag = True
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _emit_price(self, asset_id: str, price: float, force: bool = False) -> None:
        """Emit price_updated, dropping repeats and capping the per-asset rate."""
        now  = time.monotonic()
        prev = self._last_emit.get(asset_id)
        if prev is not None:
            if prev[1] == price:
                return
            if not force and now - prev[0] < _PRICE_MIN_GAP_S:
                return
        self._last_emit[asset_id] = (now, price)
        self.price_updated.emit(asset_id, price)

    # ── Thread entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            import websocket as _ws_lib   # websocket-client
        except ImportError:
            # Emit disconnected so the UI shows "No stream" rather than crashing.
            self.stream_disconnected.emit()
            return

        while not self._stop_flag:
            _ping_timer: list = [None]   # wrapped in list so nested functions can reassign

            def _cancel_ping() -> None:
                t = _ping_timer[0]
                if t is not None:
                    t.cancel()
                _ping_timer[0] = None

            def _schedule_ping(ws) -> None:
                _cancel_ping()
                if self._stop_flag:
                    return

                def _fire():
                    if self._stop_flag:
                        return
                    try:
                        ws.send("PING")
                    except Exception:
                        return
                    _schedule_ping(ws)   # reschedule

                t = threading.Timer(_PING_INTERVAL_S, _fire)
                t.daemon = True
                t.start()
                _ping_timer[0] = t

            def on_open(ws):
                self._ws = ws
                # Subscribe to our token IDs with custom_feature_enabled=True
                # to receive market_resolved and best_bid_ask events in addition
                # to the standard price_change and last_trade_price events.
                ws.send(json.dumps({
                    "assets_ids":            self._token_ids,
                    "type":                  "market",
                    "custom_feature_enabled": True,
                }))
                _schedule_ping(ws)
                self.stream_connected.emit()

            def on_message(ws, raw: str):
                if raw == "PONG":
                    return
                # Busy books send hundreds of book/price_change messages a
                # second. Parsing each one holds the GIL and starves the UI
                # thread, and the throttle would drop most of them anyway, so
                # skip the parse inside the throttle window. Trades and
                # resolutions are always parsed.
                if ("last_trade_price" not in raw and "market_resolved" not in raw
                        and time.monotonic() - self._last_parse < _PRICE_MIN_GAP_S):
                    return
                self._last_parse = time.monotonic()
                try:
                    data = json.loads(raw)
                except Exception:
                    return

                if isinstance(data, list):   # initial snapshot arrives as a list
                    data = data[0] if data and isinstance(data[0], dict) else {}
                if not isinstance(data, dict):
                    return
                etype = data.get("event_type", "")

                if etype == "last_trade_price":
                    asset_id = data.get("asset_id", "")
                    price    = float(data.get("price") or 0)
                    side     = data.get("side", "")
                    if asset_id and price > 0:
                        self._emit_price(asset_id, price)
                        self.trade_occurred.emit(asset_id, side)

                elif etype == "price_change":
                    # Each price_changes entry is a separate token
                    for pc in data.get("price_changes", []):
                        asset_id = pc.get("asset_id", "")
                        mid      = _book_mid(pc)
                        if asset_id and mid is not None:
                            self._emit_price(asset_id, mid)

                elif etype == "market_resolved":
                    winning_outcome = data.get("winning_outcome", "")
                    # assets_ids contains all token IDs for the resolved market
                    for tid in data.get("assets_ids", []):
                        self.market_resolved.emit(str(tid), winning_outcome)

            def on_error(ws, error):
                pass   # reconnect loop handles recovery

            def on_close(ws, code, msg):
                _cancel_ping()
                self._ws = None
                self.stream_disconnected.emit()

            try:
                app = _ws_lib.WebSocketApp(
                    _WS_URL,
                    on_open    = on_open,
                    on_message = on_message,
                    on_error   = on_error,
                    on_close   = on_close,
                )
                app.run_forever()
            except Exception:
                pass

            _cancel_ping()
            # Interruptible reconnect delay: wake every 100 ms so stop()
            # can exit quickly instead of blocking for the full 5 s.
            if not self._stop_flag:
                deadline = _RECONNECT_DELAY * 10   # × 100 ms
                for _ in range(deadline):
                    if self._stop_flag:
                        break
                    self.msleep(100)
