import json
import os
from pathlib import Path
from typing import Mapping


class AuthConfigError(ValueError):
    pass


def load_auth_config(config_path: Path) -> dict:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AuthConfigError(f"Authentication config not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise AuthConfigError("Authentication config is not valid JSON") from error

    if not isinstance(config, dict):
        raise AuthConfigError("Authentication config must be a JSON object")
    return config


def get_token(
    provider: str,
    config: Mapping[str, object],
    environment: Mapping[str, str] | None = None,
) -> str:
    provider_config = config.get(provider)
    if not isinstance(provider_config, dict):
        raise AuthConfigError(f"No authentication config for provider: {provider}")

    token_env = provider_config.get("token_env")
    if not isinstance(token_env, str) or not token_env:
        raise AuthConfigError(f"Missing token_env for provider: {provider}")

    token = (environment or os.environ).get(token_env)
    if not token:
        raise AuthConfigError(
            f"Environment variable {token_env} is not set for {provider}"
        )
    return token
