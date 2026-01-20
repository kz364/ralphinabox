"""Data models for sandbox interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SandboxResources:
    vcpu: int
    memory_gib: int
    disk_gib: int


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True)
class FileEntry:
    name: str
    is_dir: bool
    size: int
    mod_time: Optional[float]
