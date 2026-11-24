"""Read private role configuration as data, never as executable Python."""

import json
from pathlib import Path
from urllib.parse import urlsplit


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
    "meta_muse": ("META_API_KEY", "MUSE_MODEL", "META_BASE_URL"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_MODEL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
}
DEFAULT_PROVIDER = "meta_muse"


def check_provider_url(value):
    """The model key is sent here, so accept only a plain HTTPS endpoint."""
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("META_BASE_URL must be a plain HTTPS URL without credentials or query")


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
    provider = config.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
    if provider not in PROVIDER_KEYS:
        raise ValueError("LLM_PROVIDER must be 'meta_muse', 'gemini', or 'deepseek'")
    role_key = f"{role.upper()}_API_KEY"
    provider_names = PROVIDER_KEYS[provider]
    required = {"LEDGER_BASE_URL", role_key, *provider_names}
    if set(config) - required - {"LLM_PROVIDER", "STATE_DIR"} or not required <= config.keys():
        raise ValueError("Configuration contains unknown names or another role's key")
    if config["LEDGER_BASE_URL"].rstrip("/") != "https://ledger.chanyeun.com/api/v1":
        raise ValueError("Use the canonical Ledger HTTPS API base URL")
    needed = [role_key] if check_only else [role_key, *provider_names]
    if any(config[k].startswith("PASTE_") for k in needed):
        raise ValueError("Replace placeholders in your private configuration")
    if provider == "meta_muse" and not check_only:
        check_provider_url(config["META_BASE_URL"])
    config["LLM_PROVIDER"] = provider
    config["STATE_DIR"] = str((path.parent / config.get("STATE_DIR", ".state")).resolve())
    return config
