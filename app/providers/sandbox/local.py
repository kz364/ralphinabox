"""Local sandbox provider using the host filesystem and subprocesses."""

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
        self._base_dir = Path(base_dir) if base_dir else None
        self._sandboxes: dict[str, Path] = {}

    def _get_root(self, sandbox_id: str) -> Path:
        try:
            return self._sandboxes[sandbox_id]
        except KeyError as exc:
            raise ValueError(f"Unknown sandbox id: {sandbox_id}") from exc

    def _resolve_path(self, sandbox_id: str, path: str) -> Path:
        root = self._get_root(sandbox_id).resolve()
        target = Path(path)
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path {path} escapes sandbox root {root}") from exc
        return target

    def _run(
        self,
        sandbox_id: str,
        command: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> ExecResult:
        root = self._get_root(sandbox_id)
        run_cwd = self._resolve_path(sandbox_id, cwd) if cwd else root
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                list(command),
                cwd=run_cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = int((time.monotonic() - start) * 1000)
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + "\nCommand timed out."
            return ExecResult(
                exit_code=124,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration,
            )
        duration = int((time.monotonic() - start) * 1000)
        return ExecResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration,
        )

    def create_sandbox(
        self,
        name: str,
        resources: SandboxResources,
        image: str | None = None,
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        sandbox_id = f"{name}-{uuid.uuid4().hex}"
        base_dir = self._base_dir
        root = (
            Path(tempfile.mkdtemp(prefix=f"ralph-{name}-", dir=base_dir))
            if base_dir
            else Path(tempfile.mkdtemp(prefix=f"ralph-{name}-"))
        )
        self._sandboxes[sandbox_id] = root
        if env:
            env_path = root / ".ralph" / "sandbox-env.txt"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(
                "\n".join(f"{key}={value}" for key, value in env.items()),
                encoding="utf-8",
            )
        if labels:
            labels_path = root / ".ralph" / "sandbox-labels.txt"
            labels_path.parent.mkdir(parents=True, exist_ok=True)
            labels_path.write_text(
                "\n".join(f"{key}={value}" for key, value in labels.items()),
                encoding="utf-8",
            )
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
        return self._run(
            sandbox_id=sandbox_id,
            command=command,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
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
        with file_path.open(open_mode) as handle:
            handle.write(data)
        if mode is not None:
            file_path.chmod(mode)

    def list_files(self, sandbox_id: str, path: str) -> Sequence[FileEntry]:
        dir_path = self._resolve_path(sandbox_id, path)
        entries: list[FileEntry] = []
        for entry in os.scandir(dir_path):
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
        target = self._resolve_path(sandbox_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._inject_auth(url, auth)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_url, str(target)])
        result = self._run(sandbox_id, command)
        if result.exit_code != 0:
            raise RuntimeError(f"git clone failed: {result.stderr}")

    def git_status(self, sandbox_id: str, path: str) -> str:
        result = self._run(
            sandbox_id,
            [
                "git",
                "-C",
                str(self._resolve_path(sandbox_id, path)),
                "status",
                "--porcelain",
            ],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git status failed: {result.stderr}")
        return result.stdout

    def git_diff(self, sandbox_id: str, path: str) -> str:
        result = self._run(
            sandbox_id,
            ["git", "-C", str(self._resolve_path(sandbox_id, path)), "diff"],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git diff failed: {result.stderr}")
        return result.stdout

    def git_checkout_new_branch(
        self, sandbox_id: str, path: str, branch_name: str
    ) -> None:
        result = self._run(
            sandbox_id,
            [
                "git",
                "-C",
                str(self._resolve_path(sandbox_id, path)),
                "checkout",
                "-b",
                branch_name,
            ],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git checkout failed: {result.stderr}")

    def git_commit(self, sandbox_id: str, path: str, message: str) -> str:
        repo_path = str(self._resolve_path(sandbox_id, path))
        result = self._run(
            sandbox_id,
            [
                "git",
                "-C",
                repo_path,
                "-c",
                "user.name=Ralph",
                "-c",
                "user.email=ralph@local",
                "commit",
                "-m",
                message,
            ],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git commit failed: {result.stderr}")
        sha_result = self._run(sandbox_id, ["git", "-C", repo_path, "rev-parse", "HEAD"])
        if sha_result.exit_code != 0:
            raise RuntimeError(f"git rev-parse failed: {sha_result.stderr}")
        return sha_result.stdout.strip()

    def git_push(
        self,
        sandbox_id: str,
        path: str,
        remote: str,
        branch: str,
        auth: dict[str, str] | None = None,
    ) -> None:
        push_target = self._inject_auth(remote, auth)
        result = self._run(
            sandbox_id,
            [
                "git",
                "-C",
                str(self._resolve_path(sandbox_id, path)),
                "push",
                push_target,
                branch,
            ],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git push failed: {result.stderr}")

    def get_preview_link(self, sandbox_id: str, port: int) -> str | None:
        return None

    @staticmethod
    def _inject_auth(url: str, auth: dict[str, str] | None) -> str:
        if not auth:
            return url
        token = auth.get("token")
        if not token:
            return url
        if url.startswith("https://"):
            return url.replace("https://", f"https://{token}@", 1)
        return url
