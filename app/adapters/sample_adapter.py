import json
from pathlib import Path
from typing import List, Tuple

from app.models import ActivePosition, ResolvedPosition

SAMPLE_DIR = Path(__file__).parent.parent.parent / "sample_data"


def load_active_positions() -> List[ActivePosition]:
    path = SAMPLE_DIR / "sample_wallet_positions.json"
    with open(path) as f:
        data = json.load(f)
    return [ActivePosition(**item) for item in data]


def load_resolved_positions() -> List[ResolvedPosition]:
    path = SAMPLE_DIR / "sample_resolved_positions.json"
    with open(path) as f:
        data = json.load(f)
    return [ResolvedPosition(**item) for item in data]


def load_all() -> Tuple[List[ActivePosition], List[ResolvedPosition]]:
    return load_active_positions(), load_resolved_positions()
