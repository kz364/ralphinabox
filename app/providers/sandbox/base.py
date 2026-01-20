"""Sandbox provider interface."""

from __future__ import annotations

from typing import Protocol, Sequence

from app.models.sandbox import ExecResult, FileEntry, SandboxResources


class SandboxProvider(Protocol):
    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        ...

    def delete_sandbox(self, sandbox_id: str) -> None:
        ...

    def start_sandbox(self, sandbox_id: str) -> None:
        ...

    def stop_sandbox(self, sandbox_id: str) -> None:
        ...

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        ...

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        ...

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        ...

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        ...

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        ...

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        ...

    def git_status(self, sandbox_id: str, path: str) -> str:
        ...

    def git_diff(self, sandbox_id: str, path: str) -> str:
        ...

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        ...

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        ...

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        ...

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        ...
