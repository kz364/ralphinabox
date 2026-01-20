"""Local sandbox provider implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Sequence

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self) -> None:
        self._sandboxes: dict[str, Path] = {}

    def _get_root(self, sandbox_id: str) -> Path:
        try:
            return self._sandboxes[sandbox_id]
        except KeyError as exc:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}") from exc

    def _resolve_path(self, sandbox_id: str, path: str) -> Path:
        root = self._get_root(sandbox_id)
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return root / candidate

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid.uuid4().hex[:8]}"
        sandbox_root = Path(tempfile.mkdtemp(prefix=f"{name}-"))
        self._sandboxes[sandbox_id] = sandbox_root
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        root = self._get_root(sandbox_id)
        shutil.rmtree(root, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._get_root(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._get_root(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        root = self._get_root(sandbox_id)
        exec_cwd = Path(cwd) if cwd else root
        if not exec_cwd.is_absolute():
            exec_cwd = root / exec_cwd
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        start = time.monotonic()
        completed = subprocess.run(
            list(command),
            cwd=exec_cwd,
            env=exec_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
        )

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        resolved = self._resolve_path(sandbox_id, path)
        return resolved.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        resolved = self._resolve_path(sandbox_id, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "ab" if append else "wb"
        with open(resolved, open_mode) as handle:
            handle.write(data)
        if mode is not None:
            resolved.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        resolved = self._resolve_path(sandbox_id, path)
        if not resolved.exists():
            return []
        entries: list[FileEntry] = []
        for entry in resolved.iterdir():
            stats = entry.stat()
            entries.append(
                FileEntry(
                    name=entry.name,
                    is_dir=entry.is_dir(),
                    size=stats.st_size,
                    mod_time=stats.st_mtime,
                )
            )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        resolved = self._resolve_path(sandbox_id, path)
        resolved.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        clone_path = self._resolve_path(sandbox_id, path)
        clone_path.parent.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, str(clone_path)])
        self.exec(sandbox_id, command)

    def git_status(self, sandbox_id: str, path: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        result = self.exec(sandbox_id, ["git", "-C", str(repo_path), "status", "--porcelain"])
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        result = self.exec(sandbox_id, ["git", "-C", str(repo_path), "diff"])
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        repo_path = self._resolve_path(sandbox_id, path)
        self.exec(sandbox_id, ["git", "-C", str(repo_path), "checkout", "-b", branch_name])

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        self.exec(sandbox_id, ["git", "-C", str(repo_path), "add", "-A"])
        self.exec(sandbox_id, ["git", "-C", str(repo_path), "commit", "-m", message])
        result = self.exec(sandbox_id, ["git", "-C", str(repo_path), "rev-parse", "HEAD"])
        return result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        repo_path = self._resolve_path(sandbox_id, path)
        self.exec(sandbox_id, ["git", "-C", str(repo_path), "push", remote, branch])

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        return None
