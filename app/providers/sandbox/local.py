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
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path(
            tempfile.mkdtemp(prefix="ralph-sandbox-")
        )
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
        sandbox_id = f"local-{uuid.uuid4()}"
        sandbox_path = self._base_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        shutil.rmtree(sandbox_path, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

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
        working_dir = sandbox_path / cwd if cwd else sandbox_path
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        start = time.monotonic()
        try:
            result = subprocess.run(
                list(command),
                cwd=str(working_dir),
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return ExecResult(
                exit_code=124,
                stdout=stdout,
                stderr=stderr,
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
        target_path = self._resolve_path(sandbox_id, path)
        if not target_path.exists():
            return []
        entries: list[FileEntry] = []
        for child in target_path.iterdir():
            stat_info = child.stat()
            entries.append(
                FileEntry(
                    name=child.name,
                    is_dir=child.is_dir(),
                    size=stat_info.st_size,
                    mod_time=stat_info.st_mtime,
                )
            )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        target_path = self._resolve_path(sandbox_id, path)
        target_path.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        target_path = sandbox_path / path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._apply_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_url, str(target_path)])
        self._run_command(command, cwd=str(sandbox_path))

    def git_status(self, sandbox_id: str, path: str) -> str:
        result = self._run_command(["git", "status", "--porcelain"], cwd=self._cwd(sandbox_id, path))
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        result = self._run_command(["git", "diff"], cwd=self._cwd(sandbox_id, path))
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        self._run_command([
            "git",
            "checkout",
            "-b",
            branch_name,
        ], cwd=self._cwd(sandbox_id, path))

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        self._run_command(["git", "add", "-A"], cwd=self._cwd(sandbox_id, path))
        result = self._run_command(
            ["git", "commit", "-m", message], cwd=self._cwd(sandbox_id, path)
        )
        return result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        remote_target = self._apply_auth(remote, auth)
        self._run_command(
            ["git", "push", remote_target, branch],
            cwd=self._cwd(sandbox_id, path),
        )

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._get_sandbox_path(sandbox_id)
        return None

    def _get_sandbox_path(self, sandbox_id: str) -> Path:
        sandbox_path = self._sandboxes.get(sandbox_id)
        if not sandbox_path:
            raise ValueError(f"Unknown sandbox id: {sandbox_id}")
        return sandbox_path

    def _resolve_path(self, sandbox_id: str, path: str) -> Path:
        sandbox_path = self._get_sandbox_path(sandbox_id)
        target = sandbox_path / path
        return target

    def _cwd(self, sandbox_id: str, path: str) -> str:
        return str(self._resolve_path(sandbox_id, path))

    def _run_command(
        self,
        command: Sequence[str],
        cwd: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Command failed")
        return result

    def _apply_auth(self, url: str, auth: dict[str, str] | None) -> str:
        if not auth:
            return url
        token = auth.get("token") if isinstance(auth, dict) else None
        if not token or not url.startswith("https://"):
            return url
        return url.replace("https://", f"https://{token}@", 1)
