"""GitHub SCM provider backed by the GitHub REST API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from app.models.scm import PullRequestInfo
from app.providers.scm.base import ScmProvider


class GitHubProvider(ScmProvider):
    def __init__(self, token: str | None = None, repo: str | None = None) -> None:
        self._token = token or os.getenv("GITHUB_PAT") or os.getenv("GITHUB_TOKEN")
        self._repo = repo
        self._base_url = "https://api.github.com"

    def _ensure_token(self) -> str:
        if not self._token:
            raise ValueError("GitHub token is required (set GITHUB_PAT or GITHUB_TOKEN).")
        return self._token

    def _ensure_repo(self) -> str:
        if not self._repo:
            raise ValueError("Repository is required for this operation.")
        return self._repo

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        token = self._ensure_token()
        url = f"{self._base_url}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("User-Agent", "ralph-sandbox")
        request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise RuntimeError(f"GitHub API error {exc.code}: {body}") from exc

    def validate_auth(self) -> None:
        self._request("GET", "/user")

    def get_repo_default_branch(self, repo: str) -> str:
        response = self._request("GET", f"/repos/{repo}")
        if not isinstance(response, dict) or "default_branch" not in response:
            raise RuntimeError("Unexpected response from GitHub API.")
        return response["default_branch"]

    def open_pr(
        self,
        repo: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        draft: bool = False,
        labels: list[str] | None = None,
    ) -> PullRequestInfo:
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft,
        }
        response = self._request("POST", f"/repos/{repo}/pulls", payload)
        if not isinstance(response, dict) or "number" not in response:
            raise RuntimeError("Unexpected response from GitHub API.")
        pr_number = response["number"]
        pr_url = response.get("html_url", "")
        if labels:
            self._request(
                "POST",
                f"/repos/{repo}/issues/{pr_number}/labels",
                {"labels": labels},
            )
        self._repo = repo
        return PullRequestInfo(url=pr_url, number=pr_number)

    def update_pr(self, pr_number: int, title: str | None = None, body: str | None = None) -> None:
        if title is None and body is None:
            return
        repo = self._ensure_repo()
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        self._request("PATCH", f"/repos/{repo}/pulls/{pr_number}", payload)

    def comment_pr(self, pr_number: int, body: str) -> None:
        repo = self._ensure_repo()
        self._request(
            "POST",
            f"/repos/{repo}/issues/{pr_number}/comments",
            {"body": body},
        )

    def get_pr_checks(self, pr_number: int) -> str:
        repo = self._ensure_repo()
        pr = self._request("GET", f"/repos/{repo}/pulls/{pr_number}")
        if not isinstance(pr, dict):
            raise RuntimeError("Unexpected response from GitHub API.")
        sha = pr.get("head", {}).get("sha")
        if not sha:
            return "unknown"
        check_data = self._request("GET", f"/repos/{repo}/commits/{sha}/check-runs")
        runs = []
        if isinstance(check_data, dict):
            runs = check_data.get("check_runs", [])
        conclusions = [run.get("conclusion") for run in runs if isinstance(run, dict)]
        if any(conclusion in {"failure", "cancelled", "timed_out"} for conclusion in conclusions):
            return "failure"
        if any(conclusion in {None, "queued", "in_progress"} for conclusion in conclusions):
            return "pending"
        if conclusions:
            return "success"
        return "unknown"

    def set_commit_status(
        self,
        sha: str,
        state: str,
        description: str,
        target_url: str | None = None,
    ) -> None:
        repo = self._ensure_repo()
        payload = {"state": state, "description": description}
        if target_url:
            payload["target_url"] = target_url
        self._request("POST", f"/repos/{repo}/statuses/{sha}", payload)
