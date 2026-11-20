from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "postgresql+asyncpg://loopp:loopp@localhost:5432/loopp"

    llm_provider: str = "groq"
    llm_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    llm_max_retries: int = 3
    llm_retry_base_seconds: float = 1.0

    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dims: int = 384
    rag_cosine_threshold: float = 0.28
    rag_top_k: int = 5

    agent_max_cycles: int = 8
    agent_turn_timeout_seconds: int = 90

    demo_customer_id: str = "cust_pro_001"
    demo_customer_name: str = "Alex Rivera"
    demo_customer_email: str = "alex.rivera@example.com"
    demo_tier: str = "Pro"

    # Voice (Phase 3)
    voice_backend: str = "auto"  # auto | local | hosted
    voice_stt: str = "auto"  # auto (follow voice_backend) | local | groq
    voice_max_utterance_seconds: float = 15.0
    voice_input_sample_rate: int = 16000
    voice_vad_threshold: float = 0.5
    voice_tts_voice: str = "alba"
    voice_lazy_load: bool = True

    # Security
    session_secret: str = "dev-only-change-me"
    session_ttl_seconds: int = 60 * 60 * 12

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_llm_api_key(self) -> str:
        provider = self.llm_provider.lower().strip()
        if provider == "groq":
            return self.groq_api_key or self.llm_api_key
        if provider in {"anthropic", "claude"}:
            return self.llm_api_key or self.anthropic_api_key
        return self.llm_api_key or self.groq_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
