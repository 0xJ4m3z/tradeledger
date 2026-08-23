"""Wallet address display formatting.

Extracted so both UI layers can share it — previously this one-liner was
private to the desktop app's `WalletPanel` (`_mask_address` in
app/ui/wallet_panel.py). Same masking convention: `0x1234...abcde`.
"""


def mask_wallet_address(address: str) -> str:
    """Privacy-safe display form of a wallet address.

    Returns the input unchanged if it's too short to usefully mask (e.g. the
    web app's "sample" placeholder wallet) rather than producing a nonsense
    truncation like "sample...".
    """
    if len(address) < 11:
        return address
    return f"{address[:6]}...{address[-5:]}"
