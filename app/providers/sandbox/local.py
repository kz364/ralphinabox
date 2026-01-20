"""Local sandbox provider."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse, urlunparse

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.cwd() / ".ralph" / "sandboxes"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, Path] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid.uuid4().hex}"
        root = self._base_dir / sandbox_id
        root.mkdir(parents=True, exist_ok=False)
        self._sandboxes[sandbox_id] = root
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        root = self._resolve_root(sandbox_id)
        shutil.rmtree(root, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._resolve_root(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._resolve_root(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        root = self._resolve_root(sandbox_id)
        resolved_cwd = root / cwd if cwd else root
        resolved_cwd = resolved_cwd.resolve()
        if root not in resolved_cwd.parents and resolved_cwd != root:
            raise ValueError("cwd must resolve inside sandbox root")
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        start = time.monotonic()
        completed = subprocess.run(
            list(command),
            cwd=resolved_cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
        )

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        file_path = self._resolve_path(sandbox_id, path)
        return file_path.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        file_path = self._resolve_path(sandbox_id, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "ab" if append else "wb"
        with open(file_path, open_mode) as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(file_path, mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        dir_path = self._resolve_path(sandbox_id, path)
        if not dir_path.exists():
            return []
        entries: list[FileEntry] = []
        with os.scandir(dir_path) as listing:
            for entry in listing:
                stat = entry.stat()
                entries.append(
                    FileEntry(
                        name=entry.name,
                        is_dir=entry.is_dir(),
                        size=stat.st_size,
                        mod_time=stat.st_mtime,
                    )
                )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        dir_path = self._resolve_path(sandbox_id, path)
        dir_path.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        root = self._resolve_root(sandbox_id)
        target = self._resolve_path(sandbox_id, path)
        clone_url = self._apply_git_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_url, str(target)])
        self._run_git(command, cwd=root)

    def git_status(self, sandbox_id: str, path: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        return self._run_git(["git", "status", "--porcelain=v1"], cwd=repo_path)

    def git_diff(self, sandbox_id: str, path: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        return self._run_git(["git", "diff"], cwd=repo_path)

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        repo_path = self._resolve_path(sandbox_id, path)
        self._run_git(["git", "checkout", "-b", branch_name], cwd=repo_path)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        repo_path = self._resolve_path(sandbox_id, path)
        self._run_git(["git", "add", "-A"], cwd=repo_path)
        self._run_git(["git", "commit", "-m", message], cwd=repo_path)
        return self._run_git(["git", "rev-parse", "HEAD"], cwd=repo_path).strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        repo_path = self._resolve_path(sandbox_id, path)
        push_remote = self._apply_git_auth(remote, auth)
        self._run_git(["git", "push", push_remote, branch], cwd=repo_path)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        return None

    def _resolve_root(self, sandbox_id: str) -> Path:
        if sandbox_id not in self._sandboxes:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}")
        return self._sandboxes[sandbox_id]

    def _resolve_path(self, sandbox_id: str, path: str) -> Path:
        root = self._resolve_root(sandbox_id)
        resolved = (root / path).resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("path must resolve inside sandbox root")
        return resolved

    def _run_git(self, command: Sequence[str], cwd: Path) -> str:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Git command failed ({' '.join(command)}): {completed.stderr}"
            )
        return completed.stdout

    def _apply_git_auth(self, url: str, auth: dict[str, str] | None) -> str:
        if not auth:
            return url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return url
        netloc = parsed.netloc
        if "token" in auth:
            netloc = f"{auth['token']}@{parsed.hostname}"
        elif "username" in auth and "password" in auth:
            netloc = f"{auth['username']}:{auth['password']}@{parsed.hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))
