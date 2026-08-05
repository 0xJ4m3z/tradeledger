"""Shared Polymarket link helpers for all position tables.

Read-only — opens the system browser only.
No private keys, trades, wallet connections, or transactions.

Notes:
    _ROLE_SLUG  (UserRole)     — Polymarket event slug stored on market QTableWidgetItems
    _ROLE_TITLE (UserRole + 1) — clean market title (without the 📝 indicator suffix)
    Both are set by each table's _populate_row / _market_cell helper.
"""
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QTableWidgetItem

from app.services.polymarket_links import polymarket_url_for_slug

# Custom Qt item-data roles used across all position tables.
_ROLE_SLUG  = Qt.ItemDataRole.UserRole       # Polymarket eventSlug (str | None)
_ROLE_TITLE = Qt.ItemDataRole.UserRole + 1   # clean market title, without any note emoji

# Emoji appended to the market cell text when a note exists.
NOTE_INDICATOR = "  📝"

MENU_STYLE = """
QMenu {
    background-color: #1c2128;
    color: #c9d1d9;
    border: 2px solid #484f58;
    padding: 2px;
    font-size: 13px;
}
QMenu::item {
    padding: 5px 14px;
}
QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #6e7681;
}
"""

_MENU_MIN_WIDTH = 0


def open_polymarket(slug: Optional[str]) -> None:
    """Open the Polymarket event page for slug in the system browser."""
    url = polymarket_url_for_slug(slug)
    if url:
        QDesktopServices.openUrl(QUrl(url))


def apply_note_indicator(mkt_item: QTableWidgetItem, market: str, note: Optional[str]) -> None:
    """Update a market cell's display text and tooltip to reflect a note.

    Always stores the clean *market* title in _ROLE_TITLE so slug-lookup code
    can retrieve it without stripping the emoji suffix.

    Args:
        mkt_item: The QTableWidgetItem for the market column.
        market:   The clean market title (no emoji).
        note:     The note text, or None / "" to remove the indicator.
    """
    mkt_item.setData(_ROLE_TITLE, market)
    slug = mkt_item.data(_ROLE_SLUG)
    has_link = bool(slug)
    has_note = bool(note and note.strip())

    if has_note:
        mkt_item.setText(market + NOTE_INDICATOR)
        parts = [f"📝 {note.strip()}"]
        if has_link:
            parts.append("Ctrl+click or right-click to open on Polymarket")
        mkt_item.setToolTip("\n\n".join(parts))
    else:
        mkt_item.setText(market)
        if has_link:
            mkt_item.setToolTip("Ctrl+click or right-click to open on Polymarket")
        else:
            mkt_item.setToolTip("")


def show_table_context_menu(table, pos, market_col: int = 0) -> None:
    """Show context menu for a QTableWidget market row.

    Menu items:
      • "Open on Polymarket" (only if the cell has a slug)
      • "Add Note…" / "Edit Note…"
      • "Clear Note" (only if a note exists)

    Reads slug from _ROLE_SLUG and the clean market title from _ROLE_TITLE (with
    fallback to raw cell text) on the market column cell.
    """
    from app.services import notes as _notes  # avoid circular import at module level

    item = table.itemAt(pos)
    if item is None:
        return
    mkt_item = table.item(item.row(), market_col)
    if mkt_item is None:
        return

    slug   = mkt_item.data(_ROLE_SLUG)
    market = mkt_item.data(_ROLE_TITLE) or mkt_item.text().replace(NOTE_INDICATOR, "").strip()

    current_note = _notes.get(market)

    menu = QMenu(table)
    menu.setStyleSheet(MENU_STYLE)

    open_action  = None
    clear_action = None

    if slug:
        open_action = menu.addAction("Open on Polymarket")
        menu.addSeparator()

    note_label  = "Edit Note…" if current_note else "Add Note…"
    note_action = menu.addAction(note_label)
    if current_note:
        clear_action = menu.addAction("Clear Note")

    chosen = menu.exec(table.viewport().mapToGlobal(pos))
    if chosen is None:
        return

    if chosen == open_action:
        open_polymarket(slug)
        return

    if chosen == note_action:
        new_note, ok = QInputDialog.getMultiLineText(
            table,
            "Trade Note",
            market,
            current_note or "",
        )
        if not ok:
            return
        if new_note.strip():
            _notes.set(market, new_note.strip())
            apply_note_indicator(mkt_item, market, new_note.strip())
        else:
            # User cleared the text box — treat as delete
            _notes.delete(market)
            apply_note_indicator(mkt_item, market, None)
        return

    if clear_action and chosen == clear_action:
        _notes.delete(market)
        apply_note_indicator(mkt_item, market, None)


def attach_table_links(table, market_col: int = 0) -> None:
    """Wire Polymarket right-click, Ctrl+click, and Add Note onto a QTableWidget.

    Call once after the table widget is created. The market cell (column
    market_col) must have the slug stored as _ROLE_SLUG for the Polymarket
    link to appear.  Notes always appear regardless of whether a slug is set.
    """
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(
        lambda pos: show_table_context_menu(table, pos, market_col)
    )

    def _on_click(item):
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
            return
        mkt_item = table.item(item.row(), market_col)
        slug = mkt_item.data(_ROLE_SLUG) if mkt_item else None
        open_polymarket(slug)

    table.itemClicked.connect(_on_click)
