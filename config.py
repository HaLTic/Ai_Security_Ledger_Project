"""Read private role configuration as data, never as executable Python."""

import json
from pathlib import Path


def strict_json(text):
    def constant(_):
        raise ValueError("Non-finite JSON number")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return json.loads(text, parse_constant=constant, object_pairs_hook=pairs)


PROVIDER_KEYS = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_MODEL"),
}


def load_config(path, role, *, check_only=False):
    path = Path(path).resolve()
    if path.stat().st_size > 16384:
        raise ValueError("Configuration exceeds 16 KiB")
    config = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or any(
        not isinstance(v, str) or not v.strip() or "\x00" in v for v in config.values()
    ):
        raise ValueError("Configuration requires non-empty string values")
    config = {k: v.strip() for k, v in config.items()}
    provider = config.get("LLM_PROVIDER", "deepseek").lower()
    if provider not in PROVIDER_KEYS:
        raise ValueError("LLM_PROVIDER must be 'deepseek' or 'gemini'")
    role_key = f"{role.upper()}_API_KEY"
    provider_key, provider_model = PROVIDER_KEYS[provider]
    required = {"LEDGER_BASE_URL", role_key, provider_key, provider_model}
    if set(config) - required - {"LLM_PROVIDER", "STATE_DIR"} or not required <= config.keys():
        raise ValueError("Configuration contains unknown names or another role's key")
    if config["LEDGER_BASE_URL"].rstrip("/") != "https://ledger.chanyeun.com/api/v1":
        raise ValueError("Use the canonical Ledger HTTPS API base URL")
    needed = [role_key] if check_only else [role_key, provider_key, provider_model]
    if any(config[k].startswith("PASTE_") for k in needed):
        raise ValueError("Replace placeholders in your private configuration")
    config["LLM_PROVIDER"] = provider
    config["STATE_DIR"] = str((path.parent / config.get("STATE_DIR", ".state")).resolve())
    return config
