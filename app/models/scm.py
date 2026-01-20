"""Data models for SCM interactions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestInfo:
    url: str
    number: int
