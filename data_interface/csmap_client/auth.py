"""Load local API credentials without depending on the working directory."""

import os
from pathlib import Path
from typing import Mapping


DEFAULT_KEY_FILE = Path(__file__).resolve().parent.parent / "api_key.txt"
KEY_PLACEHOLDER = "PASTE_YOUR_CSMAP_API_KEY_HERE"


def _validate_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("API key must be a string")
    key = value.strip()
    if not key or key == KEY_PLACEHOLDER:
        raise ValueError("Replace the placeholder in api_key.txt with your personal CSMaP API key")
    if any(not 33 <= ord(character) <= 126 for character in key):
        raise ValueError("API key must be a single token without whitespace or control characters")
    return key


def _read_key_file(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        raise ValueError("API key file must be UTF-8 plain text") from None
    return _validate_key(value)


def authorization_headers(
    headers: Mapping[str, str] | None,
    api_key: str | None,
    api_key_file: str | Path | None,
) -> dict[str, str]:
    result = dict(headers or {})
    authorization = [name for name in result if name.lower() == "authorization"]
    if authorization:
        if len(authorization) != 1:
            raise ValueError("Provide only one Authorization header")
        if api_key is not None or api_key_file is not None:
            raise ValueError("Use either an Authorization header or api_key/api_key_file, not both")
        value = result[authorization[0]]
        if not isinstance(value, str) or not value.strip() or any(character in value for character in "\r\n"):
            raise ValueError("Authorization header must be a non-empty single line")
        return result

    if api_key is not None:
        key = _validate_key(api_key)
    elif api_key_file is not None:
        key = _read_key_file(Path(api_key_file).expanduser())
    elif os.environ.get("CSMAP_API_KEY", "").strip():
        key = _validate_key(os.environ["CSMAP_API_KEY"])
    elif DEFAULT_KEY_FILE.exists():
        key = _read_key_file(DEFAULT_KEY_FILE)
    else:
        raise ValueError(
            f"CSMaP API key required: fill {DEFAULT_KEY_FILE}, set CSMAP_API_KEY, "
            "or pass api_key/api_key_file"
        )
    result["Authorization"] = f"Bearer {key}"
    return result
