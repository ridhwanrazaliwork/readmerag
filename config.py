import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "ridhwanrazaliwork")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LITELLM_MODEL = os.getenv("LITELLM_MODEL", "openrouter/google/gemini-2.5-flash-lite")
LITELLM_EMBEDDING_MODEL = os.getenv(
    "LITELLM_EMBEDDING_MODEL", "openrouter/qwen3-embedding-8b"
)

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

LITELLM_DEBUG = os.getenv("LITELLM_DEBUG", "false").lower() == "true"

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
