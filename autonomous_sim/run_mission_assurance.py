from __future__ import annotations

import os
import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "mission_assurance_api:app",
        host=os.environ.get("COUCH_AUTONOMY_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("COUCH_AUTONOMY_BIND_PORT", "8794")),
        reload=os.environ.get("COUCH_AUTONOMY_RELOAD", "1") == "1",
    )
