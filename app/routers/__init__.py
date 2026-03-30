from fastapi import FastAPI
from app.routers.webhook import router as webhook_router
from app.routers.sessions import router as sessions_router


def register_routes(app: FastAPI):
    app.include_router(webhook_router)
    app.include_router(sessions_router)
