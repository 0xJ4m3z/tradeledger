"""Polymarket authenticated user WebSocket stream.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/user using CLOB API
credentials (apiKey, secret, passphrase — no private key, no wallet signing).

Emits Qt signals when Trade Events or Order Events arrive for the authenticated
wallet — useful for instant notification of your own buys and sells.

Protocol:
  - Send auth subscription on connect (type="user").
  - Send text "PING" every 10 s; server replies "PONG".
  - Trade events arrive when a CLOB order is MATCHED / MINED / CONFIRMED.
  - Order events arrive on order placement, fill, and cancellation.
  - Reconnects automatically after disconnect (5 s delay).

Security:
  TradeLedger is read-only.  Credentials are passed in as plain strings and
  used only to authenticate this read-only stream.  No private keys, no wallet
  signatures, no transactions.
"""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import QThread, Signal

_WS_URL          = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
_PING_INTERVAL_S = 10
_RECONNECT_DELAY = 5


class UserStreamThread(QThread):
    """Authenticated Polymarket user WebSocket stream.

    Signals (all safe to connect to main-thread slots):
      trade_event(dict)          — raw trade event dict; emitted for every status
                                   update (MATCHED, MINED, CONFIRMED, …)
      order_event(dict)          — raw order event dict
      stream_connected()         — WebSocket (re)connected and auth sent
      stream_disconnected()      — connection dropped; will reconnect shortly
      stream_error(str)          — non-recoverable error (e.g. bad credentials)
    """

    trade_event         = Signal(dict)
    order_event         = Signal(dict)
    stream_connected    = Signal()
    stream_disconnected = Signal()
    stream_error        = Signal(str)

    def __init__(self, api_key: str, secret: str, passphrase: str, parent=None):
        super().__init__(parent)
        self._api_key    = api_key
        self._secret     = secret
        self._passphrase = passphrase
        self._stop_flag  = False
        self._ws         = None

    # ── Public ─────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the thread to stop and close the socket without reconnecting."""
        self._stop_flag = True
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    # ── Thread entry point ─────────────────────────────────────────────────────

    def run(self) -> None:
        import websocket as _ws_lib   # websocket-client

        while not self._stop_flag:
            _ping_timer: list = [None]

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
                    _schedule_ping(ws)

                t = threading.Timer(_PING_INTERVAL_S, _fire)
                t.daemon = True
                t.start()
                _ping_timer[0] = t

            def on_open(ws):
                self._ws = ws
                ws.send(json.dumps({
                    "auth": {
                        "apiKey":     self._api_key,
                        "secret":     self._secret,
                        "passphrase": self._passphrase,
                    },
                    "markets": [],   # empty = all markets for this wallet
                    "type":    "user",
                }))
                _schedule_ping(ws)
                self.stream_connected.emit()

            def on_message(ws, raw: str):
                if raw == "PONG":
                    return
                try:
                    data = json.loads(raw)
                except Exception:
                    return

                # The user stream may send a single object or a list of events.
                events = data if isinstance(data, list) else [data]
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    # event_type (lowercase) or type (uppercase) — handle both
                    raw_type = (
                        event.get("event_type")
                        or event.get("type")
                        or ""
                    ).upper()
                    if raw_type == "TRADE":
                        self.trade_event.emit(event)
                    elif raw_type == "ORDER":
                        self.order_event.emit(event)

            def on_error(ws, error):
                err_str = str(error)
                # Detect auth failures so the caller can surface a clear message
                if any(x in err_str for x in ("401", "403", "Unauthorized", "Forbidden")):
                    self.stream_error.emit(f"Auth failed: {error}")

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
            if not self._stop_flag:
                self.msleep(_RECONNECT_DELAY * 1000)
