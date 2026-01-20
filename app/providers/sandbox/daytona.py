"""Daytona sandbox provider placeholder."""

from __future__ import annotations

from typing import Sequence

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class DaytonaProvider(SandboxProvider):
    def __init__(self) -> None:
        raise NotImplementedError("Implement Daytona SDK integration")

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        raise NotImplementedError

    def delete_sandbox(self, sandbox_id: str) -> None:
        raise NotImplementedError

    def start_sandbox(self, sandbox_id: str) -> None:
        raise NotImplementedError

    def stop_sandbox(self, sandbox_id: str) -> None:
        raise NotImplementedError

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        raise NotImplementedError

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        raise NotImplementedError

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        raise NotImplementedError

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        raise NotImplementedError

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        raise NotImplementedError

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        raise NotImplementedError

    def git_status(self, sandbox_id: str, path: str) -> str:
        raise NotImplementedError

    def git_diff(self, sandbox_id: str, path: str) -> str:
        raise NotImplementedError

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        raise NotImplementedError

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        raise NotImplementedError

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        raise NotImplementedError

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        raise NotImplementedError
