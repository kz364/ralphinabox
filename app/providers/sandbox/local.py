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
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="ralph-sandbox-"))
        self._sandboxes: dict[str, Path] = {}
        self._env: dict[str, dict[str, str]] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid4().hex}"
        sandbox_path = self._base_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=False)
        self._sandboxes[sandbox_id] = sandbox_path
        self._env[sandbox_id] = dict(env or {})
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        shutil.rmtree(sandbox_path, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)
        self._env.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._get_sandbox_path(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._get_sandbox_path(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved_cwd = self._resolve_path(sandbox_path, cwd) if cwd else sandbox_path
        exec_env = os.environ.copy()
        exec_env.update(self._env.get(sandbox_id, {}))
        if env:
            exec_env.update(env)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                list(command),
                cwd=resolved_cwd,
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
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecResult(
                exit_code=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Command timed out after {timeout_s}s",
                duration_ms=duration_ms,
            )

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        return resolved.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "ab" if append else "wb"
        with resolved.open(write_mode) as handle:
            handle.write(data)
        if mode is not None:
            resolved.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        entries: list[FileEntry] = []
        for item in resolved.iterdir():
            stat = item.stat()
            entries.append(
                FileEntry(
                    name=item.name,
                    is_dir=item.is_dir(),
                    size=stat.st_size,
                    mod_time=stat.st_mtime,
                )
            )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        resolved.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, str(resolved)])
        self._run_command(command, cwd=sandbox_path)

    def git_status(self, sandbox_id: str, path: str) -> str:
        return self._run_git(sandbox_id, path, ["status", "--porcelain=v1"])

    def git_diff(self, sandbox_id: str, path: str) -> str:
        return self._run_git(sandbox_id, path, ["diff"])

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        self._run_git(sandbox_id, path, ["checkout", "-b", branch_name])

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        self._run_git(sandbox_id, path, ["add", "-A"])
        self._run_git(sandbox_id, path, ["commit", "-m", message])
        return self._run_git(sandbox_id, path, ["rev-parse", "HEAD"]).strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        self._run_git(sandbox_id, path, ["push", remote, branch])

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        return None

    def _get_sandbox_path(self, sandbox_id: str) -> Path:
        try:
            return self._sandboxes[sandbox_id]
        except KeyError as exc:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}") from exc

    def _resolve_path(self, sandbox_root: Path, path: str) -> Path:
        resolved = (sandbox_root / path).resolve()
        if sandbox_root not in resolved.parents and resolved != sandbox_root:
            raise ValueError("Path escapes sandbox root")
        return resolved

    def _run_git(self, sandbox_id: str, path: str, args: Sequence[str]) -> str:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        resolved = self._resolve_path(sandbox_path, path)
        return self._run_command(["git", *args], cwd=resolved)

    def _run_command(self, command: Sequence[str], cwd: Path) -> str:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout
