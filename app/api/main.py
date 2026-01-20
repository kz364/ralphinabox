from fastapi import FastAPI

app = FastAPI(title="ralph-sandbox")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
