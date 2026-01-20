"""LiteLLM client wrapper."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


class LiteLLMClient:
    def __init__(self, config_path: str = "config/models.yaml") -> None:
        self._config_path = Path(config_path)
        self._profiles = self._load_profiles()

    def _load_profiles(self) -> dict[str, dict[str, Any]]:
        if not self._config_path.exists():
            return {}
        yaml_spec = importlib.util.find_spec("yaml")
        if yaml_spec is None:
            raise RuntimeError("PyYAML is required to load model profiles.")
        yaml = importlib.import_module("yaml")
        with self._config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            return {}
        return profiles

    def get_profile(self, name: str) -> dict[str, Any]:
        profile = self._profiles.get(name)
        if not profile:
            raise KeyError(f"Unknown model profile: {name}")
        return profile

    def completion(
        self,
        profile_name: str,
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> Any:
        profile = self.get_profile(profile_name)
        litellm_spec = importlib.util.find_spec("litellm")
        if litellm_spec is None:
            raise RuntimeError("litellm must be installed to request completions.")
        litellm = importlib.import_module("litellm")
        params: dict[str, Any] = {
            "model": profile["litellm_model"],
            "messages": messages,
            "temperature": profile.get("temperature", 0.2),
            "max_tokens": profile.get("max_output_tokens", 2048),
        }
        params.update(overrides)
        return litellm.completion(**params)
