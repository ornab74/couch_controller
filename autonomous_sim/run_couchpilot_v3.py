from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "couchpilot_v3_api:app",
        host=os.environ.get("COUCH_AUTONOMY_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("COUCH_AUTONOMY_BIND_PORT", "8792")),
        reload=os.environ.get("COUCH_AUTONOMY_RELOAD", "1") == "1",
    )
