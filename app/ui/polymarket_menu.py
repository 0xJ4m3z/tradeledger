"""Shared Polymarket link helpers for all position tables.

Read-only — opens the system browser only.
No private keys, trades, wallet connections, or transactions.
"""
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu

from app.services.polymarket_links import polymarket_url_for_slug

MENU_STYLE = """
QMenu {
    background-color: #1c2128;
    color: #c9d1d9;
    border: 2px solid #484f58;
    padding: 3px;
    font-size: 13px;
}
QMenu::item {
    padding: 5px 20px;
    text-align: center;
}
QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #6e7681;
}
"""

_MENU_MIN_WIDTH = 200


def open_polymarket(slug: Optional[str]) -> None:
    """Open the Polymarket event page for slug in the system browser."""
    url = polymarket_url_for_slug(slug)
    if url:
        QDesktopServices.openUrl(QUrl(url))


def show_table_context_menu(table, pos, market_col: int = 0) -> None:
    """Show 'Open on Polymarket' context menu for a QTableWidget row.

    Reads slug from Qt.ItemDataRole.UserRole on the market column cell.
    No-op if the hovered row has no slug.
    """
    item = table.itemAt(pos)
    if item is None:
        return
    mkt_item = table.item(item.row(), market_col)
    slug = mkt_item.data(Qt.ItemDataRole.UserRole) if mkt_item else None
    if not slug:
        return
    menu = QMenu(table)  # parent required on Windows for stylesheet to apply
    menu.setStyleSheet(MENU_STYLE)
    menu.setMinimumWidth(_MENU_MIN_WIDTH)
    action = menu.addAction("Open on Polymarket")
    if menu.exec(table.viewport().mapToGlobal(pos)) == action:
        open_polymarket(slug)


def attach_table_links(table, market_col: int = 0) -> None:
    """Wire Polymarket right-click and Ctrl+click onto a QTableWidget.

    Call once after the table widget is created. The market cell
    (column market_col) must have the slug stored as UserRole for
    the menu to appear. Safe to call when no rows have slugs.
    """
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(
        lambda pos: show_table_context_menu(table, pos, market_col)
    )

    def _on_click(item):
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
            return
        mkt_item = table.item(item.row(), market_col)
        slug = mkt_item.data(Qt.ItemDataRole.UserRole) if mkt_item else None
        open_polymarket(slug)

    table.itemClicked.connect(_on_click)
