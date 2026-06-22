import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "ridhwanrazaliwork")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LITELLM_MODEL = os.getenv("LITELLM_MODEL", "openrouter/google/gemma-4-26b-a4b-it:free")
LITELLM_EMBEDDING_MODEL = os.getenv(
    "LITELLM_EMBEDDING_MODEL", "openrouter/nvidia/llama-nemotron-embed-vl-1b-v2:free"
)

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

LITELLM_DEBUG = os.getenv("LITELLM_DEBUG", "false").lower() == "true"

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
