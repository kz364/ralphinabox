"""Local sandbox provider implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self) -> None:
        self._root_dir = Path(tempfile.mkdtemp(prefix="ralph-sandbox-"))
        self._sandboxes: dict[str, Path] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid4().hex}"
        sandbox_path = self._root_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        shutil.rmtree(sandbox_path, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._ensure_sandbox(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._ensure_sandbox(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_cwd = self._resolve_path(sandbox_path, cwd) if cwd else sandbox_path
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                list(command),
                cwd=resolved_cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return ExecResult(
                exit_code=124,
                stdout=stdout,
                stderr=stderr or "Command timed out",
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ExecResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
        )

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        return resolved_path.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = "ab" if append else "wb"
        with resolved_path.open(file_mode) as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(resolved_path, mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        entries: list[FileEntry] = []
        for entry in resolved_path.iterdir():
            stat_result = entry.stat()
            entries.append(
                FileEntry(
                    name=entry.name,
                    is_dir=entry.is_dir(),
                    size=stat_result.st_size,
                    mod_time=stat_result.st_mtime,
                )
            )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        resolved_path.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        command = ["git", "clone", url, str(resolved_path)]
        if branch:
            command.insert(2, "--branch")
            command.insert(3, branch)
        self._run_git(command, sandbox_path, auth)

    def git_status(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        output = self._run_git(
            ["git", "status", "--porcelain", "-b"],
            resolved_path,
            None,
        )
        return output

    def git_diff(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        return self._run_git(["git", "diff"], resolved_path, None)

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        self._run_git(["git", "checkout", "-b", branch_name], resolved_path, None)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        self._run_git(["git", "add", "-A"], resolved_path, None)
        self._run_git(["git", "commit", "-m", message], resolved_path, None)
        sha = self._run_git(["git", "rev-parse", "HEAD"], resolved_path, None)
        return sha.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._ensure_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        self._run_git(["git", "push", remote, branch], resolved_path, auth)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._ensure_sandbox(sandbox_id)
        return None

    def _ensure_sandbox(self, sandbox_id: str) -> Path:
        sandbox_path = self._sandboxes.get(sandbox_id)
        if not sandbox_path:
            raise ValueError(f"Unknown sandbox id: {sandbox_id}")
        return sandbox_path

    @staticmethod
    def _resolve_path(sandbox_path: Path, path: str | None) -> Path:
        if path is None:
            return sandbox_path
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return sandbox_path / candidate

    @staticmethod
    def _run_git(
        command: Sequence[str],
        cwd: Path,
        auth: dict[str, str] | None,
    ) -> str:
        env = os.environ.copy()
        if auth:
            env.update({k: v for k, v in auth.items() if isinstance(v, str)})
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout
