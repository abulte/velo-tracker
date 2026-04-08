"""Garmin Connect API client."""

import base64
import os
import tempfile
from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = Path(__file__).parent / "garmin_tokens"


def get_client() -> Garmin:
    """Return an authenticated Garmin client.

    Loads tokens from either:
    - garmin_tokens/ directory (local dev)
    - GARMIN_OAUTH1_TOKEN / GARMIN_OAUTH2_TOKEN env vars (Dokku, base64-encoded)
    """
    client = Garmin()

    oauth1 = os.environ.get("GARMIN_OAUTH1_TOKEN")
    oauth2 = os.environ.get("GARMIN_OAUTH2_TOKEN")

    if oauth1 and oauth2:
        # Dokku: decode env vars into a temp dir and load
        tmp = tempfile.mkdtemp(prefix="garmin_tokens_")
        Path(tmp, "oauth1_token.json").write_text(
            base64.b64decode(oauth1).decode()
        )
        Path(tmp, "oauth2_token.json").write_text(
            base64.b64decode(oauth2).decode()
        )
        client.garth.load(tmp)
    elif TOKEN_DIR.exists():
        # Local dev: load from file
        client.garth.load(str(TOKEN_DIR))
    else:
        raise RuntimeError(
            "No Garmin tokens found. Run `python cli.py login` first, "
            "or set GARMIN_OAUTH1_TOKEN / GARMIN_OAUTH2_TOKEN env vars."
        )

    client.display_name = client.garth.profile["displayName"]
    return client
