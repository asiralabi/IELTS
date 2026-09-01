from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI IELTS Instructor & Examiner"
    debug: bool = False

    database_url: str = "sqlite:///./data/ielts.db"

    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    # How far back the repetition penalty looks, in tokens, and how hard it
    # pushes. Ollama defaults to 64 / 1.1, and 64 is SHORTER than the cycle the
    # fine-tuned generator loops on (~85 tokens), so the penalty never fires --
    # the model repeats a sentence until it hits the token cap. 320 spans
    # roughly three cycles.
    ollama_repeat_last_n: int = 320
    ollama_repeat_penalty: float = 1.15
    # Task-specific fine-tuned checkpoints, served by ollama alongside the
    # general model. Each falls back to ollama_model when blank. These exist
    # because a checkpoint trained only to generate Listening parts is worse
    # than the general model at every other job in the app.
    generator_model: str = ""
    evaluator_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # Reasoning models spend their token budget thinking BEFORE they write, and
    # a budget too small to cover both comes back with `finish_reason="length"`
    # and an EMPTY `content` -- which reaches the app as "No JSON object found
    # in response: ''". Measured 2026-08-27 on gpt-oss-120b, one 900-word
    # script asked for at max_tokens=16384:
    #
    #   default (high)  10793 completion tokens, 43145 chars of reasoning, 72s
    #   medium           1552 completion tokens,  1703 chars of reasoning, 12s
    #   low              1934 completion tokens,    75 chars of reasoning, 13s
    #                    ^ and the LONGEST answer of the three
    #
    # Blank means the parameter is not sent at all, because a model that does
    # not know it answers 400. Set it per provider in .env.
    openai_reasoning_effort: str = ""
    llm_temperature: float = 0.4
    # 2048 was cutting off 650-900 word IELTS passages mid-JSON; 4096 gives
    # comfortable headroom for a full passage + 8-13 questions + answer key.
    llm_max_tokens: int = 4096
    # Per-request timeout in seconds; local CPU inference can be very slow
    llm_timeout: float = 600.0
    # The fine-tunes are local CPU models generating far more tokens than the
    # general model ever does (a full listening part is ~2-3k tokens at ~8
    # tok/s), so they need a budget well past the warm-pool fail-fast cap.
    finetune_timeout: float = 900.0

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

    @property
    def jwt_secret_is_default(self) -> bool:
        """Whether tokens are being signed with the secret that ships in git.

        Anyone holding it can mint a token for any user, so this is a
        credential in name only until it is overridden.
        """
        return self.jwt_secret == _DEFAULT_JWT_SECRET

    def ensure_data_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.assets_dir).mkdir(parents=True, exist_ok=True)
        Path(self.tts_cache_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
