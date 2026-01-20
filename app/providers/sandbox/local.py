"""Local sandbox provider implementation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Sequence
from uuid import uuid4

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


@dataclass(frozen=True)
class _SandboxRecord:
    sandbox_id: str
    root: Path


class LocalProvider(SandboxProvider):
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path(
            tempfile.mkdtemp(prefix="ralph-local-")
        )
        self._sandboxes: dict[str, _SandboxRecord] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid4().hex[:8]}"
        root = self._base_dir / sandbox_id
        root.mkdir(parents=True, exist_ok=False)
        record = _SandboxRecord(sandbox_id=sandbox_id, root=root)
        self._sandboxes[sandbox_id] = record
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        record = self._get_record(sandbox_id)
        shutil.rmtree(record.root, ignore_errors=True)
        self._sandboxes.pop(sandbox_id, None)

    def start_sandbox(self, sandbox_id: str) -> None:
        self._get_record(sandbox_id)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self._get_record(sandbox_id)

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        root = self._get_record(sandbox_id).root
        workdir = self._resolve_path(sandbox_id, cwd) if cwd else root
        start = time.monotonic()
        process = subprocess.run(
            list(command),
            cwd=workdir,
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
        target = self._resolve_path(sandbox_id, path)
        return target.read_bytes()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        data: bytes,
        mode: int | None = None,
        append: bool = False,
    ) -> None:
        target = self._resolve_path(sandbox_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "ab" if append else "wb"
        with target.open(write_mode) as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(target, mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        target = self._resolve_path(sandbox_id, path)
        entries: list[FileEntry] = []
        for entry in target.iterdir():
            stat_info = entry.stat()
            entries.append(
                FileEntry(
                    name=entry.name,
                    is_dir=entry.is_dir(),
                    size=stat_info.st_size,
                    mod_time=stat_info.st_mtime,
                )
            )
        return entries

    def mkdirs(self, sandbox_id: str, path: str) -> None:
        target = self._resolve_path(sandbox_id, path)
        target.mkdir(parents=True, exist_ok=True)

    def git_clone(
        self,
        sandbox_id: str,
        url: str,
        path: str,
        branch: str | None = None,
        auth: dict[str, str] | None = None,
    ) -> None:
        target = self._resolve_path(sandbox_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._apply_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_url, str(target)])
        self._run_git(sandbox_id, command)

    def git_status(self, sandbox_id: str, path: str) -> str:
        output = self._run_git(sandbox_id, ["git", "status", "--porcelain"], cwd=path)
        return output.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        output = self._run_git(sandbox_id, ["git", "diff", "--patch"], cwd=path)
        return output.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        self._run_git(
            sandbox_id, ["git", "checkout", "-b", branch_name], cwd=path
        )

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        self._run_git(sandbox_id, ["git", "add", "-A"], cwd=path)
        self._run_git(sandbox_id, ["git", "commit", "-m", message], cwd=path)
        output = self._run_git(sandbox_id, ["git", "rev-parse", "HEAD"], cwd=path)
        return output.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        remote_url = self._resolve_remote_url(sandbox_id, remote, path, auth)
        self._run_git(sandbox_id, ["git", "push", remote_url, branch], cwd=path)

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        self._get_record(sandbox_id)
        return None

    def _get_record(self, sandbox_id: str) -> _SandboxRecord:
        if sandbox_id not in self._sandboxes:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}")
        return self._sandboxes[sandbox_id]

    def _resolve_path(self, sandbox_id: str, path: str) -> Path:
        root = self._get_record(sandbox_id).root.resolve()
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError(f"Path escapes sandbox: {path}")
        return resolved

    def _merge_env(self, env: dict[str, str] | None) -> dict[str, str]:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return merged

    def _apply_auth(self, url: str, auth: dict[str, str] | None) -> str:
        if not auth or not url.startswith("https://"):
            return url
        token = auth.get("token")
        username = auth.get("username")
        password = auth.get("password")
        credential = None
        if token:
            credential = token
        elif username and password:
            credential = f"{username}:{password}"
        if not credential:
            return url
        return url.replace("https://", f"https://{credential}@", 1)

    def _run_git(
        self, sandbox_id: str, command: Sequence[str], cwd: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        result = self.exec(sandbox_id, command, cwd=cwd)
        if result.exit_code != 0:
            raise RuntimeError(
                "Git command failed: "
                f"{' '.join(command)}\n{result.stderr.strip()}"
            )
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _resolve_remote_url(
        self,
        sandbox_id: str,
        remote: str,
        repo_path: str,
        auth: dict[str, str] | None,
    ) -> str:
        if remote.startswith("http://") or remote.startswith("https://"):
            return self._apply_auth(remote, auth)
        output = self.exec(
            sandbox_id,
            ["git", "remote", "get-url", remote],
            cwd=repo_path,
        )
        if output.exit_code != 0:
            raise RuntimeError(f"Unknown git remote: {remote}")
        return self._apply_auth(output.stdout.strip(), auth)
