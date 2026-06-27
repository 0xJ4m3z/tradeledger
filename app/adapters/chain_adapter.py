# Stub for future read-only external API integration.
# Fetches public market/position data by wallet address — no private keys ever used.

from typing import List, Tuple

from app.models import ActivePosition, ResolvedPosition


def load_active_positions(wallet_address: str) -> List[ActivePosition]:
    raise NotImplementedError("External API adapter not implemented in v0.1.")


def load_resolved_positions(wallet_address: str) -> List[ResolvedPosition]:
    raise NotImplementedError("External API adapter not implemented in v0.1.")


def load_all(wallet_address: str) -> Tuple[List[ActivePosition], List[ResolvedPosition]]:
    return load_active_positions(wallet_address), load_resolved_positions(wallet_address)
