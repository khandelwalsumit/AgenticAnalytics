from __future__ import annotations

import json
import logging
import os
import threading

import requests
from google.oauth2.credentials import Credentials

import config

logger = logging.getLogger(__name__)

try:
    import vertexai
except Exception as exc:  # pragma: no cover - depends on runtime env
    vertexai = None
    _VERTEX_IMPORT_ERROR = exc
else:
    _VERTEX_IMPORT_ERROR = None

_AUTH_LOCK = threading.Lock()
_AUTH_INITIALIZED = False


def get_coin_token(timeout_seconds: int = 30) -> str:
    """Fetch an access token from COIN.

    Expected env vars:
    - CLIENT_ID
    - CLIENT_SECRET
    - CLIENT_SCOPES
    """
    client_id = str(os.getenv("CLIENT_ID", "")).strip()
    client_secret = str(os.getenv("CLIENT_SECRET", "")).strip()
    client_scopes = str(os.getenv("CLIENT_SCOPES", "")).strip()

    if not client_id or not client_secret or not client_scopes:
        raise RuntimeError(
            "Missing COIN credentials. Set CLIENT_ID, CLIENT_SECRET, and CLIENT_SCOPES."
        )

    url = f"https://coin-uat.ls.dyn.nsroot.net/token/v2/{client_id}"
    headers = {
        "accept": "*/*",
        "Content-Type": "application/json",
    }
    payload = {
        "clientSecret": client_secret,
        "clientScopes": [client_scopes],
    }

    response = requests.post(url, json=payload, headers=headers, verify=False, timeout=timeout_seconds)
    response.raise_for_status()

    body = response.text.strip()
    token = body.strip('"')

    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            token = str(
                parsed.get("access_token")
                or parsed.get("token")
                or parsed.get("id_token")
                or token
            ).strip()
        elif isinstance(parsed, str):
            token = parsed.strip().strip('"')
    except (json.JSONDecodeError, ValueError):
        pass

    if not token:
        raise RuntimeError("COIN token endpoint returned an empty token.")

    return token


def authenticate_vertexai(force: bool = False) -> None:
    """Initialize Vertex AI with R2D2 auth metadata.

    This is safe for concurrent callers and no-ops after first successful init,
    unless force=True.
    """
    global _AUTH_INITIALIZED

    if vertexai is None:
        raise RuntimeError(
            "vertexai package is not available. "
            f"Install it in runtime env. Import error: {_VERTEX_IMPORT_ERROR}"
        )

    with _AUTH_LOCK:
        if _AUTH_INITIALIZED and not force:
            return

        if not config.R2D2_PROJECT or not config.R2D2_ENDPOINT or not config.USERNAME:
            raise RuntimeError(
                "Missing R2D2 settings. Set R2D2_PROJECT, R2D2_ENDPOINT, and USERNAME."
            )

        token = get_coin_token()
        credentials = Credentials(token=token)

        vertexai.init(
            project=config.R2D2_PROJECT,
            api_transport="rest",
            api_endpoint=config.R2D2_ENDPOINT,
            credentials=credentials,
            request_metadata=[("x-r2d2-user", config.USERNAME)],
        )
        _AUTH_INITIALIZED = True
        logger.info("Initialized Vertex AI with R2D2 authentication.")
