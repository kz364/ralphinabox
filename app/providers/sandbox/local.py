"""Local sandbox provider."""

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
        self._root = Path(tempfile.mkdtemp(prefix="ralph-local-"))
        self._sandboxes: dict[str, Path] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = uuid.uuid4().hex
        sandbox_path = self._root / f"{name}-{sandbox_id}"
        sandbox_path.mkdir(parents=True, exist_ok=False)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._sandboxes.pop(sandbox_id, None)
        if sandbox_path is None:
            return
        shutil.rmtree(sandbox_path, ignore_errors=True)

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
        working_dir = self._resolve_path(sandbox_path, cwd) if cwd else sandbox_path
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        start = time.monotonic()
        result = subprocess.run(
            list(command),
            cwd=working_dir,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        return target.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with target.open("ab") as handle:
                handle.write(data)
        else:
            target.write_bytes(data)
        if mode is not None:
            target.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._require_sandbox(sandbox_id)
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
        sandbox_path = self._require_sandbox(sandbox_id)
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
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._apply_git_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command += ["--branch", branch]
        command += [clone_url, str(target)]
        self._run_git(command, cwd=sandbox_path)

    def git_status(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        result = self._run_git(["git", "-C", str(target), "status", "--short"], cwd=target)
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        result = self._run_git(["git", "-C", str(target), "diff"], cwd=target)
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        self._run_git(["git", "-C", str(target), "checkout", "-b", branch_name], cwd=target)

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        self._run_git(["git", "-C", str(target), "commit", "-m", message], cwd=target)
        result = self._run_git(["git", "-C", str(target), "rev-parse", "HEAD"], cwd=target)
        return result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        target = self._resolve_path(sandbox_path, path)
        remote_url = self._apply_git_auth(remote, auth)
        if remote_url != remote:
            self._run_git(
                ["git", "-C", str(target), "remote", "set-url", "origin", remote_url],
                cwd=target,
            )
        self._run_git(["git", "-C", str(target), "push", "origin", branch], cwd=target)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._require_sandbox(sandbox_id)
        return None

    def _require_sandbox(self, sandbox_id: str) -> Path:
        sandbox_path = self._sandboxes.get(sandbox_id)
        if sandbox_path is None:
            raise ValueError(f"Unknown sandbox id: {sandbox_id}")
        return sandbox_path

    def _resolve_path(self, sandbox_path: Path, path: str | None) -> Path:
        if path is None:
            return sandbox_path
        relative = path.lstrip("/")
        target = (sandbox_path / relative).resolve()
        if sandbox_path not in target.parents and target != sandbox_path:
            raise ValueError("Path escapes sandbox root")
        return target

    def _run_git(self, command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    def _apply_git_auth(self, url: str, auth: dict[str, str] | None) -> str:
        if not auth:
            return url
        token = auth.get("token")
        if token and url.startswith("https://") and "@" not in url:
            return url.replace("https://", f"https://{token}@", 1)
        username = auth.get("username")
        password = auth.get("password")
        if username and password and url.startswith("https://") and "@" not in url:
            return url.replace("https://", f"https://{username}:{password}@", 1)
        return url
