import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv



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


    from app.routers import register_routes
    register_routes(app)

    from .config import settings

    return app

# Create the FastAPI app instance
app = create_app()