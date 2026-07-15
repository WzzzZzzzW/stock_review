from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    glm_api_key: str
    deepseek_api_key: str = ""
    qwen_api_key: str = ""        # 通义千问 / DashScope（OpenAI 兼容端点）
    ark_api_key: str = ""
    ark_responses_url: str = "https://ark.cn-beijing.volces.com/api/v3/responses"
    ark_web_search: bool = True

    class Config:
        env_file = (".env", ".env.ark")


settings = Settings()
