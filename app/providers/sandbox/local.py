"""Local sandbox provider implementation."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import time
from typing import Mapping, Sequence
from uuid import uuid4

from app.models.sandbox import ExecResult, FileEntry, SandboxResources
from app.providers.sandbox.base import SandboxProvider


class LocalProvider(SandboxProvider):
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="ralph-local-"))
        self._sandboxes: dict[str, Path] = {}

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"local-{uuid4()}"
        sandbox_path = self._base_dir / f"{name}-{sandbox_id}"
        sandbox_path.mkdir(parents=True, exist_ok=False)
        self._sandboxes[sandbox_id] = sandbox_path
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox_path = self._require_sandbox(sandbox_id)
        shutil.rmtree(sandbox_path)
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
        command_cwd = self._resolve_path(sandbox_path, cwd) if cwd else sandbox_path
        merged_env = self._merge_env(env)
        start_time = time.monotonic()
        result = subprocess.run(
            list(command),
            cwd=command_cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return ExecResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )

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
        file_mode = "ab" if append else "wb"
        with resolved_path.open(file_mode) as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(resolved_path, mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        sandbox_path = self._require_sandbox(sandbox_id)
        resolved_path = self._resolve_path(sandbox_path, path)
        entries: list[FileEntry] = []
        for entry in resolved_path.iterdir():
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
        destination = self._resolve_path(sandbox_path, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch, "--single-branch"])
        command.extend([url, str(destination)])
        subprocess.run(command, check=True, capture_output=True, text=True)

    def git_status(self, sandbox_id: str, path: str) -> str:
        output = self._run_git(sandbox_id, path, ["status", "--porcelain"])
        return output.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        output = self._run_git(sandbox_id, path, ["diff"])
        return output.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        self._run_git(sandbox_id, path, ["checkout", "-b", branch_name])

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        self._run_git(sandbox_id, path, ["add", "--all"])
        self._run_git(sandbox_id, path, ["commit", "-m", message])
        output = self._run_git(sandbox_id, path, ["rev-parse", "HEAD"])
        return output.stdout.strip()

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
        self._require_sandbox(sandbox_id)
        return None

    def _require_sandbox(self, sandbox_id: str) -> Path:
        if sandbox_id not in self._sandboxes:
            raise KeyError(f"Unknown sandbox id: {sandbox_id}")
        return self._sandboxes[sandbox_id]

    def _resolve_path(self, sandbox_path: Path, path: str | None) -> Path:
        if path is None or path == "":
            return sandbox_path
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = sandbox_path / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(sandbox_path.resolve()):
            raise ValueError(f"Path {path} escapes sandbox root")
        return resolved

    def _merge_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env.setdefault("GIT_AUTHOR_NAME", "ralph")
        merged_env.setdefault("GIT_AUTHOR_EMAIL", "ralph@example.com")
        merged_env.setdefault("GIT_COMMITTER_NAME", "ralph")
        merged_env.setdefault("GIT_COMMITTER_EMAIL", "ralph@example.com")
        return merged_env

    def _run_git(self, sandbox_id: str, path: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        sandbox_path = self._require_sandbox(sandbox_id)
        git_cwd = self._resolve_path(sandbox_path, path)
        return subprocess.run(
            ["git", *args],
            cwd=git_cwd,
            env=self._merge_env(None),
            check=True,
            capture_output=True,
            text=True,
        )
