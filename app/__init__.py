import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func,  create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler


load_dotenv()








def create_app():
    app = FastAPI(
        title="My API",
        description="This is my FastAPI app",
        version="1.0.0",
        docs_url=None if os.getenv('ENVIRONMENT') == 'PRODUCTION' else "/docs",
        redoc_url=None if os.getenv('ENVIRONMENT') == 'PRODUCTION' else "/redoc",
    )

    # CORS setup
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # from app.utils.utils import log_request_middleware
    # app.middleware("http")(log_request_middleware)

    from app.routers import register_routes
    register_routes(app)

    # from .database import Database
    # database = Database()

    from .config import settings
    config = settings
    global gcelery
    gcelery = create_celery()
    # initialize_redis_streams()


    return app

# Create the FastAPI app instance
app = create_app()