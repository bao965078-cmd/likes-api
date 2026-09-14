from fastapi import FastAPI

app = FastAPI(title="likes-api")

@app.get("/")
def home():
    return {
        "status": "online",
        "message": "likes-api is running"
    }

@app.get("/health")
def health():
    return {"status": "ok"}
