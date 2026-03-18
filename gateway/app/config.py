"""
Gateway Configuration
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Desktop Node connection
    DESKTOP_NODE_URL: str = "http://host.docker.internal:7777"
    DESKTOP_NODE_API_KEY: str = ""

    # CORS
    cors_allow_origins: list[str] = ["*"]

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 18789

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
