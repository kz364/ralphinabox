"""Local sandbox provider implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self) -> None:
        self._sandboxes: dict[str, Path] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_dir = Path(tempfile.mkdtemp(prefix=f"ralph-{name}-"))
        self._sandboxes[str(sandbox_dir)] = sandbox_dir
        return str(sandbox_dir)

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_dir = self._sandbox_path(sandbox_id)
        shutil.rmtree(sandbox_dir, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._sandbox_path(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._sandbox_path(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        sandbox_dir = self._sandbox_path(sandbox_id)
        resolved_cwd = sandbox_dir if cwd is None else sandbox_dir / cwd
        start = time.monotonic()
        process = subprocess.run(
            list(command),
            cwd=resolved_cwd,
            env=self._merge_env(env),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecResult(
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            duration_ms=duration_ms,
        )

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox_dir = self._sandbox_path(sandbox_id)
        return (sandbox_dir / path).read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        sandbox_dir = self._sandbox_path(sandbox_id)
        target = sandbox_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "ab" if append else "wb"
        with target.open(open_mode) as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(target, mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_dir = self._sandbox_path(sandbox_id)
        target = sandbox_dir / path
        entries: list[FileEntry] = []
        for entry in target.iterdir():
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
        sandbox_dir = self._sandbox_path(sandbox_id)
        (sandbox_dir / path).mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_dir = self._sandbox_path(sandbox_id)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, path])
        self._run_git(command, sandbox_dir, auth)

    def git_status(self, sandbox_id: str, path: str) -> str:
        sandbox_dir = self._sandbox_path(sandbox_id)
        return self._run_git(["git", "status", "--porcelain=v1"], sandbox_dir / path)

    def git_diff(self, sandbox_id: str, path: str) -> str:
        sandbox_dir = self._sandbox_path(sandbox_id)
        return self._run_git(["git", "diff"], sandbox_dir / path)

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        sandbox_dir = self._sandbox_path(sandbox_id)
        self._run_git(["git", "checkout", "-b", branch_name], sandbox_dir / path)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        sandbox_dir = self._sandbox_path(sandbox_id)
        self._run_git(["git", "add", "-A"], sandbox_dir / path)
        self._run_git(["git", "commit", "-m", message], sandbox_dir / path)
        return self._run_git(["git", "rev-parse", "HEAD"], sandbox_dir / path).strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_dir = self._sandbox_path(sandbox_id)
        self._run_git(["git", "push", remote, branch], sandbox_dir / path, auth)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._sandbox_path(sandbox_id)
        return None

    def _sandbox_path(self, sandbox_id: str) -> Path:
        sandbox_dir = self._sandboxes.get(sandbox_id)
        if sandbox_dir is None:
            sandbox_dir = Path(sandbox_id)
            if not sandbox_dir.exists():
                raise FileNotFoundError(f"Sandbox not found: {sandbox_id}")
        return sandbox_dir

    def _merge_env(self, env: dict[str, str] | None) -> dict[str, str]:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return merged

    def _run_git(
        self,
        command: Sequence[str],
        cwd: Path,
        auth: dict[str, str] | None = None,
    ) -> str:
        env = self._merge_env(auth)
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return result.stdout
