#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создание GitHub Issues через REST API или локальную заглушку."""

from __future__ import annotations

import itertools
import threading
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

    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    try:
        response = requests.post(
            f"https://api.github.com/repos/{clean_repo}/issues",
            json=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {clean_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
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
        raise GitHubIssuesError(f"GitHub вернул {response.status_code}: {detail}")

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
