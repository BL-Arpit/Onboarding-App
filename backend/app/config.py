from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: str = "./data"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    store_full_aadhaar: bool = False
    max_upload_mb: int = 10
    name_pass: float = 92.0
    name_warn: float = 80.0

    @property
    def cors_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
