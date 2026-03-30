from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from contextlib import asynccontextmanager
import os
import asyncio
from typing import AsyncGenerator

# Create a declarative base
Base = declarative_base()

DATABASE_USERNAME = os.environ.get('DATABASE_USERNAME')
DATABASE_PASSWORD = os.environ.get('DATABASE_PASSWORD')
DATABASE_HOSTNAME = os.environ.get('DATABASE_HOSTNAME')
DATABASE_NAME = os.environ.get('DATABASE_NAME')


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._engine = None
            cls._instance._sessionmaker = None
            cls._instance._loop = None  # Keep track of the loop where the engine was created
        return cls._instance

    def _initialize(self):
        """
        Lazily initialize the engine and sessionmaker in the current loop.
        """
        current_loop = asyncio.get_running_loop()

        # Reinitialize if called in a new loop
        if self._engine is None or self._loop != current_loop:
            self._engine = create_async_engine(
                f"postgresql+asyncpg://{DATABASE_USERNAME}:{DATABASE_PASSWORD}@{DATABASE_HOSTNAME}:5432/{DATABASE_NAME}",
                pool_size=50,  # Configure a connection pool
                max_overflow=100,  # Allow extra connections
                # echo=True  # Enable logging for debugging
            )
            self._sessionmaker = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            self._loop = current_loop  # Update to the current loop

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Create and yield an async session bound to the correct engine and loop.
        """
        self._initialize()
        async_session = self._sessionmaker()
        try:
            yield async_session
        finally:
            await async_session.close()