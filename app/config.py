from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEBUG: bool = True

    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_HOSTNAME: str
    DATABASE_NAME: str
    DATABASE_URI: str = ""

    AGENT_IMAGE: str = "jaas_agent_v1:latest"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    @model_validator(mode="after")
    def build_database_uri(self) -> "Settings":
        self.DATABASE_URI = (
            f"postgresql+asyncpg://{self.DATABASE_USERNAME}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOSTNAME}/{self.DATABASE_NAME}"
        )
        return self


settings = Settings()
