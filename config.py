from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    gemini_api_key: str
    database_url: str = "sqlite:///./chatbot.db"
    allowed_origins: str = "https://6cias.com,http://localhost"
    cloudinary_cloud_name: str = "dzinwey2x"
    cloudinary_api_key: str = "397936317813431"
    cloudinary_api_secret: str = "iEkqCLJ5hzTsggGKNGRG4JxxdSw"

    
    class Config:
        env_file = ".env"
    
    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

settings = Settings()