"""Local sandbox provider using local subprocesses."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Sequence

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self) -> None:
        self._sandboxes: dict[str, Path] = {}
        self._base_dir = Path(os.environ.get("RALPH_LOCAL_SANDBOX_DIR", "/tmp/ralph"))
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"local-{name}-{uuid.uuid4().hex}"
        sandbox_path = self._base_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._require_path(sandbox_id)
        shutil.rmtree(sandbox_path, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._require_path(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._require_path(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        sandbox_path = self._require_path(sandbox_id)
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        resolved_cwd = self._resolve_path(sandbox_path, cwd) if cwd else sandbox_path
        start = time.monotonic()
        completed = subprocess.run(
            list(command),
            cwd=str(resolved_cwd),
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
        sandbox_path = self._require_path(sandbox_id)
        file_path = self._resolve_path(sandbox_path, path)
        return file_path.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        sandbox_path = self._require_path(sandbox_id)
        file_path = self._resolve_path(sandbox_path, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            file_path.open("ab").write(data)
        else:
            file_path.write_bytes(data)
        if mode is not None:
            file_path.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._require_path(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
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
        sandbox_path = self._require_path(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        target.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, path])
        self.exec(sandbox_id, command)

    def git_status(self, sandbox_id: str, path: str) -> str:
        result = self.exec(sandbox_id, ["git", "status", "--porcelain=v1"], cwd=path)
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        result = self.exec(sandbox_id, ["git", "diff"], cwd=path)
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        self.exec(sandbox_id, ["git", "checkout", "-b", branch_name], cwd=path)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        self.exec(sandbox_id, ["git", "commit", "-am", message], cwd=path)
        result = self.exec(sandbox_id, ["git", "rev-parse", "HEAD"], cwd=path)
        return result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        self.exec(sandbox_id, ["git", "push", remote, branch], cwd=path)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._require_path(sandbox_id)
        return None

    def _require_path(self, sandbox_id: str) -> Path:
        if sandbox_id not in self._sandboxes:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}")
        return self._sandboxes[sandbox_id]

    def _resolve_path(self, sandbox_path: Path, path: str | None) -> Path:
        if not path:
            return sandbox_path
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return sandbox_path / candidate
