from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.demo import router as demo_router


app = FastAPI(title="PostgreSQL Deadlock Lab")
app.include_router(accounts_router)
app.include_router(demo_router)

frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=frontend_directory), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(frontend_directory / "index.html")
