"""SCM provider interface."""

from __future__ import annotations

from typing import Protocol

from app.models.scm import PullRequestInfo


class ScmProvider(Protocol):
    def validate_auth(self) -> None:
        ...

    def get_repo_default_branch(self, repo: str) -> str:
        ...

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
        ...

    def update_pr(self, pr_number: int, title: str | None = None, body: str | None = None) -> None:
        ...

    def comment_pr(self, pr_number: int, body: str) -> None:
        ...

    def get_pr_checks(self, pr_number: int) -> str:
        ...

    def set_commit_status(
        self,
        sha: str,
        state: str,
        description: str,
        target_url: str | None = None,
    ) -> None:
        ...
