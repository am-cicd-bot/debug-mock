import os


class Settings:
    SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "meridian-dispute-agent")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "gke-prod-us-central1")
    CORE_LEDGER_URL: str = os.getenv("CORE_LEDGER_URL", "http://127.0.0.1:8081")
    POLICIES_DIR: str = os.getenv(
        "POLICIES_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "policies")),
    )
    DISPUTE_DB_PATH: str = os.getenv(
        "DISPUTE_DB_PATH",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "disputes.db")),
    )

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "1.15"))

    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    INTERNAL_SERVICE_API_KEY: str = os.getenv(
        "INTERNAL_SERVICE_API_KEY", "mcb_live_internal_99481a7f3c2e0019b8d1"
    )


settings = Settings()
