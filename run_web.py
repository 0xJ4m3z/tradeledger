"""Launch the TradeLedger web app (FastAPI + Uvicorn).

    python run_web.py

Serves on http://127.0.0.1:8000 by default. See web/README.md for details.
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.main:app",
        host=os.getenv("TRADELEDGER_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("TRADELEDGER_WEB_PORT", "8000")),
        reload=bool(os.getenv("TRADELEDGER_WEB_RELOAD")),
    )
