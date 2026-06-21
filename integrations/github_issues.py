#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создание GitHub Issues через REST API или локальную заглушку."""

from __future__ import annotations

import hashlib
import itertools
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import get_logger

logger = get_logger(__name__)

_STUB_COUNTER = itertools.count(1)
_STUB_LOCK = threading.Lock()


class GitHubIssuesError(RuntimeError):
    """Ошибка при создании issue в GitHub."""


@dataclass
class IssueCreateResult:
    number: int
    html_url: str
    stub: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_number": self.number,
            "html_url": self.html_url,
            "stub": self.stub,
        }


def _github_api_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _format_github_error(
    *,
    status_code: int,
    detail: str,
    repo: str,
    token: str,
    timeout: float,
) -> str:
    if status_code != 403:
        return f"GitHub вернул {status_code}: {detail}"

    token_user = "unknown"
    permissions: dict[str, Any] | None = None
    try:
        user_response = requests.get(
            "https://api.github.com/user",
            headers=_github_api_headers(token),
            timeout=timeout,
        )
        if user_response.ok:
            token_user = str(user_response.json().get("login") or "unknown")
        repo_response = requests.get(
            f"https://api.github.com/repos/{repo}",
            headers=_github_api_headers(token),
            timeout=timeout,
        )
        if repo_response.ok:
            permissions = repo_response.json().get("permissions")
    except requests.RequestException:
        pass

    owner = repo.split("/", 1)[0] if "/" in repo else repo
    hint = (
        f"GitHub вернул 403: токен аккаунта «{token_user}» не может создавать issues "
        f"в «{repo}»."
    )
    if permissions is not None:
        hint += f" Текущие права: {permissions}."
    if token_user != owner:
        hint += (
            f" Создайте fine-grained PAT на аккаунте «{owner}» с доступом к репозиторию "
            f"«{repo}» и правом Issues: Read and write, затем обновите GITHUB_TOKEN в .env."
        )
    else:
        hint += (
            " Обновите fine-grained PAT: Repository access -> wiki_4, "
            "Permissions -> Issues -> Read and write. "
            "Либо создайте classic token со scope public_repo."
        )
    return hint


_WRITE_PROBE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WRITE_PROBE_LOCK = threading.Lock()
_WRITE_PROBE_TTL_SECONDS = 300.0


def probe_github_issue_write_access(
    token: str,
    repo: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Проверить, может ли PAT создавать issues (кэш 5 мин)."""
    clean_repo = (repo or "").strip()
    clean_token = (token or "").strip()
    if not github_issues_configured(clean_token, clean_repo):
        return {"writable": None, "hint": None}

    cache_key = f"{hashlib.sha256(clean_token.encode()).hexdigest()[:16]}:{clean_repo}"
    now = time.time()
    with _WRITE_PROBE_LOCK:
        cached = _WRITE_PROBE_CACHE.get(cache_key)
        if cached and now - cached[0] < _WRITE_PROBE_TTL_SECONDS:
            return cached[1]

    result: dict[str, Any]
    try:
        response = requests.post(
            f"https://api.github.com/repos/{clean_repo}/issues",
            json={
                "title": "[probe] write access check",
                "body": "Automated write-access probe. Safe to close.",
            },
            headers=_github_api_headers(clean_token),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        result = {"writable": False, "hint": f"Не удалось проверить доступ к GitHub: {exc}"}
    else:
        if response.status_code == 201:
            issue_number = int(response.json().get("number") or 0)
            if issue_number:
                try:
                    requests.patch(
                        f"https://api.github.com/repos/{clean_repo}/issues/{issue_number}",
                        json={"state": "closed"},
                        headers=_github_api_headers(clean_token),
                        timeout=timeout,
                    )
                except requests.RequestException:
                    pass
            result = {"writable": True, "hint": None}
        elif response.status_code == 403:
            detail = response.text[:500]
            try:
                detail = response.json().get("message") or detail
            except ValueError:
                pass
            result = {
                "writable": False,
                "hint": _format_github_error(
                    status_code=403,
                    detail=str(detail),
                    repo=clean_repo,
                    token=clean_token,
                    timeout=timeout,
                ),
            }
        else:
            detail = response.text[:500]
            try:
                detail = response.json().get("message") or detail
            except ValueError:
                pass
            result = {"writable": False, "hint": f"GitHub вернул {response.status_code}: {detail}"}

    with _WRITE_PROBE_LOCK:
        _WRITE_PROBE_CACHE[cache_key] = (now, result)
    return result


def github_issues_configured(token: str, repo: str) -> bool:
    return bool((token or "").strip() and (repo or "").strip())


def create_github_issue(
    *,
    title: str,
    body: str,
    token: str,
    repo: str,
    labels: list[str] | None = None,
    timeout: float = 20.0,
) -> IssueCreateResult:
    """
    Создать issue в GitHub или вернуть заглушку, если токен/репозиторий не заданы.
    """
    clean_repo = (repo or "").strip()
    clean_token = (token or "").strip()

    if not github_issues_configured(clean_token, clean_repo):
        return _create_stub_issue(title, body, clean_repo or "stub/repo")

    if "/" not in clean_repo:
        raise GitHubIssuesError("GITHUB_REPO должен быть в формате owner/repo")

    api_url = f"https://api.github.com/repos/{clean_repo}/issues"
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=_github_api_headers(clean_token),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GitHubIssuesError(f"Не удалось связаться с GitHub: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        try:
            detail = response.json().get("message") or detail
        except ValueError:
            pass
        raise GitHubIssuesError(
            _format_github_error(
                status_code=response.status_code,
                detail=str(detail),
                repo=clean_repo,
                token=clean_token,
                timeout=timeout,
            )
        )

    data = response.json()
    number = int(data.get("number") or 0)
    html_url = str(data.get("html_url") or "")
    if not number or not html_url:
        raise GitHubIssuesError("GitHub вернул неполный ответ")

    logger.info("Создан GitHub issue #%s в %s", number, clean_repo)
    return IssueCreateResult(number=number, html_url=html_url, stub=False)


def _create_stub_issue(title: str, body: str, repo: str) -> IssueCreateResult:
    with _STUB_LOCK:
        number = next(_STUB_COUNTER)

    owner, _, name = repo.partition("/")
    if not name:
        owner, name = "stub", repo

    html_url = f"https://github.com/{owner}/{name}/issues/{number}"
    logger.info(
        "GitHub issue stub #%s (token/repo не настроены): %s",
        number,
        title[:120],
    )
    logger.debug("Stub issue body preview: %s", body[:400])
    return IssueCreateResult(number=number, html_url=html_url, stub=True)
