from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root of the project (the folder containing /app)
_ROOT = Path(__file__).parent.parent

class Settings(BaseSettings):
    # Groq LLM
    groq_api_key: str = "YOUR_GROQ_API_KEY"
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.2
    groq_max_tokens: int = 2048
    groq_timeout: int = 60

    # JIRA
    jira_base_url: str = "https://yourorg.atlassian.net"
    jira_email: str = "you@yourorg.com"
    jira_api_token: str = "YOUR_JIRA_API_TOKEN"
    jira_project_key: str = "PROJ"
    jira_assignee_account_id: str = ""

    # Log monitoring
    error_levels: list[str] = ["ERROR", "CRITICAL", "FATAL"]

    model_config = SettingsConfigDict(
        # Absolute paths — works regardless of working directory
        env_file=[
            str(_ROOT / ".env.example"),   # fallback / dev defaults
            str(_ROOT / ".env"),            # production overrides (wins)
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
