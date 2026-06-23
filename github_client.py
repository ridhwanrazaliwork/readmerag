import logging
import httpx

import config

logger = logging.getLogger(__name__)


def _headers():
    headers = {"Accept": "application/vnd.github.raw+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return headers


def get_repos(username: str) -> list[tuple[str, str, str, list[str]]]:
    repos = []
    page = 1
    client = httpx.Client()
    try:
        while True:
            url = f"https://api.github.com/users/{username}/repos"
            params = {"per_page": 100, "page": page, "type": "public", "sort": "updated"}
            resp = client.get(url, headers=_headers(), params=params)
            if resp.status_code == 403:
                logger.warning("GitHub API rate limit hit (403). Returning %d repos.", len(repos))
                break
            resp.raise_for_status()
            page_data = resp.json()
            if not page_data:
                break
            for r in page_data:
                repos.append((
                    r["name"],
                    r.get("updated_at", ""),
                    r.get("description") or "",
                    r.get("topics", []),
                ))
            page += 1
    except httpx.HTTPError as e:
        logger.error("Failed to fetch repos: %s", e)
    finally:
        client.close()
    return repos


def fetch_readme(username: str, repo: str) -> str | None:
    url = f"https://api.github.com/repos/{username}/{repo}/readme"
    try:
        resp = httpx.get(url, headers=_headers())
        if resp.status_code == 404:
            logger.info("No README for %s/%s", username, repo)
            return None
        if resp.status_code == 403:
            logger.warning("Rate limited fetching README for %s/%s", username, repo)
            return None
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        logger.error("Failed to fetch README for %s/%s: %s", username, repo, e)
        return None
