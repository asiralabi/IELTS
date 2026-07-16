from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI IELTS Instructor & Examiner"
    debug: bool = False

    database_url: str = "sqlite:///./data/ielts.db"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.4
    # 2048 was cutting off 650-900 word IELTS passages mid-JSON; 4096 gives
    # comfortable headroom for a full passage + 8-13 questions + answer key.
    llm_max_tokens: int = 4096
    # Per-request timeout in seconds; local CPU inference can be very slow
    llm_timeout: float = 600.0

    # Listening audio (edge-tts neural voices). Synthesis is lazy + cached.
    tts_enabled: bool = True
    tts_voice_rate: str = "-6%"  # exam-realistic pacing, slightly under natural

    # Speaking transcription (faster-whisper). The system design specifies
    # Whisper Large-v3; on a CPU-only box "large-v3" is accurate but slow, so
    # this is overridable (e.g. WHISPER_MODEL=small.en for a faster dev loop).
    whisper_model: str = "large-v3"
    whisper_device: str = "cpu"  # "cuda" when a GPU is available
    whisper_compute_type: str = "int8"  # int8 on CPU; "float16" on GPU

    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    assets_dir: str = "./data/assets"
    tts_cache_dir: str = "./data/tts_cache"
    qdrant_path: str = "./data/qdrant"
    qdrant_url: str = ""
    qdrant_collection: str = "ielts_knowledge"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    rag_chunk_size: int = 650
    rag_chunk_overlap: int = 100
    rag_top_k: int = 5

    def ensure_data_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.assets_dir).mkdir(parents=True, exist_ok=True)
        Path(self.tts_cache_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
