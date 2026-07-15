from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    glm_api_key: str
    deepseek_api_key: str = ""
    qwen_api_key: str = ""        # 通义千问 / DashScope（OpenAI 兼容端点）

    class Config:
        env_file = ".env"


settings = Settings()
