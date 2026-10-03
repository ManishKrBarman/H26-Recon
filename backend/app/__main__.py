from .api import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=False)
