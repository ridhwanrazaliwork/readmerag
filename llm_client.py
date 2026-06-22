import logging

import litellm
from litellm import RateLimitError, Timeout

import config

if config.LITELLM_DEBUG:
    litellm._turn_on_debug()

logger = logging.getLogger(__name__)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    try:
        response = litellm.embedding(
            model=config.LITELLM_EMBEDDING_MODEL,
            input=texts,
            api_key=config.LITELLM_API_KEY,
        )
        return [item["embedding"] for item in response["data"]]
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return []


def chat(query: str, context: str) -> str:
    system_prompt = (
        "You are a helpful assistant answering questions about a developer's portfolio and GitHub projects. "
        "Use the following README context to answer the user's question. "
        "If the context doesn't contain relevant information, say so honestly.\n\n"
        f"### README Context ###\n{context}\n### End Context ###"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    try:
        response = litellm.completion(
            model=config.LITELLM_MODEL,
            messages=messages,
            api_key=config.LITELLM_API_KEY,
        )
        return response.choices[0].message.content
    except RateLimitError:
        logger.warning("LLM rate limit hit (429).")
        return "My system is out of free AI credits at the moment, but please check back later!"
    except Timeout:
        logger.warning("LLM request timed out.")
        return "The AI service took too long to respond. Please try again."
    except Exception as e:
        logger.error("LLM completion failed: %s", e)
        return "Sorry, something went wrong while generating a response."
