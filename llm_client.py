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


def chat(query: str, context: str, history: list[dict] | None = None,
         context_type: str = "readme") -> str:
    messages = _build_messages(query, context, history, context_type)
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


def chat_stream(
    query: str,
    context: str,
    history: list[dict] | None = None,
    context_type: str = "readme",
) -> str:
    messages = _build_messages(query, context, history, context_type)
    try:
        response = litellm.completion(
            model=config.LITELLM_MODEL,
            messages=messages,
            api_key=config.LITELLM_API_KEY,
            stream=True,
        )
        for chunk in response:
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content
    except RateLimitError:
        yield "My system is out of free AI credits at the moment, but please check back later!"
    except Timeout:
        yield "The AI service took too long to respond. Please try again."
    except Exception as e:
        logger.error("LLM stream failed: %s", e)
        yield "Sorry, something went wrong while generating a response."


def _build_messages(query, context, history, context_type):
    if context_type == "catalog":
        system_prompt = (
            "You are an AI assistant on a personal portfolio site. "
            "The user wants a summary of available projects. "
            "Use the project catalog below to answer.\n\n"
            f"### Project Catalog ###\n{context}\n### End Catalog ###"
        )
    else:
        system_prompt = (
            "You are a helpful assistant answering questions about a developer's "
            "portfolio and GitHub projects. "
            "Use the following README context to answer the user's question. "
            "If the context doesn't contain relevant information, say so honestly.\n\n"
            f"### README Context ###\n{context}\n### End Context ###"
        )
    messages = [{"role": "system", "content": system_prompt}]
    for msg in (history or []):
        messages.append(msg)
    messages.append({"role": "user", "content": query})
    return messages
