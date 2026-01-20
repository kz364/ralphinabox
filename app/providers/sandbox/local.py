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
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(
            base_dir
            if base_dir is not None
            else tempfile.mkdtemp(prefix="ralph-local-sandboxes-")
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
        sandbox_id = f"{name}-{uuid4().hex}"
        sandbox_path = self._base_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=False)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        shutil.rmtree(sandbox_path, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._require_sandbox(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._require_sandbox(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_cwd = self._resolve_path(sandbox_path, cwd)
        return self._run_command(command, resolved_cwd, env, timeout_s)

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox_path = self._require_sandbox(sandbox_id)
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
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "ab" if append else "wb"
        with resolved_path.open(open_mode) as handle:
            handle.write(data)
        if mode is not None:
            resolved_path.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        if not resolved_path.exists():
            return []
        entries: list[FileEntry] = []
        for entry in os.scandir(resolved_path):
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
        sandbox_path = self._require_sandbox(sandbox_id)
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
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._apply_git_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_url, str(resolved_path)])
        result = self._run_command(command, sandbox_path, None, None)
        self._raise_on_failure("git clone", result)

    def git_status(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        result = self._run_command(
            ["git", "-C", str(resolved_path), "status", "--porcelain"],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git status", result)
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        result = self._run_command(
            ["git", "-C", str(resolved_path), "diff"],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git diff", result)
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        result = self._run_command(
            ["git", "-C", str(resolved_path), "checkout", "-b", branch_name],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git checkout", result)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        commit_result = self._run_command(
            ["git", "-C", str(resolved_path), "commit", "-m", message],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git commit", commit_result)
        sha_result = self._run_command(
            ["git", "-C", str(resolved_path), "rev-parse", "HEAD"],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git rev-parse", sha_result)
        return sha_result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        result = self._run_command(
            ["git", "-C", str(resolved_path), "push", remote, branch],
            sandbox_path,
            None,
            None,
        )
        self._raise_on_failure("git push", result)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._require_sandbox(sandbox_id)
        return None

    def _require_sandbox(self, sandbox_id: str) -> Path:
        try:
            return self._sandboxes[sandbox_id]
        except KeyError as exc:
            raise ValueError(f"Unknown sandbox id: {sandbox_id}") from exc

    def _resolve_path(self, sandbox_path: Path, path: str | None) -> Path:
        if path is None:
            return sandbox_path
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return sandbox_path / candidate

    def _run_command(
        self,
        command: Sequence[str],
        cwd: Path,
        env: dict[str, str] | None,
        timeout_s: int | None,
    ) -> ExecResult:
        start = time.monotonic()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=merged_env,
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

    def _raise_on_failure(self, action: str, result: ExecResult) -> None:
        if result.exit_code == 0:
            return
        raise RuntimeError(
            f"{action} failed with exit code {result.exit_code}: {result.stderr}"
        )

    def _apply_git_auth(self, url: str, auth: dict[str, str] | None) -> str:
        if not auth:
            return url
        if url.startswith("https://"):
            token = auth.get("token")
            if token:
                return url.replace("https://", f"https://{token}@", 1)
            username = auth.get("username")
            password = auth.get("password")
            if username and password:
                return url.replace("https://", f"https://{username}:{password}@", 1)
        return url
