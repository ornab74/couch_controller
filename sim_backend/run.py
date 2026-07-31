import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("COUCH_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("COUCH_BIND_PORT", "8787")),
        reload=True,
    )
