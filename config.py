from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    gemini_api_key: str
    database_url: str = "sqlite:///./chatbot.db"
    allowed_origins: str = "https://6cias.com,http://localhost"
    
    class Config:
        env_file = ".env"
    
    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

settings = Settings()