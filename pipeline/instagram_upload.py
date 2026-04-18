"""Upload Reel to Instagram via Graph API.

Flow:
  1. POST /{ig_id}/media  — create media container from a public video URL
  2. GET  /{creation_id}?fields=status_code  — poll until FINISHED
  3. POST /{ig_id}/media_publish  — publish the container

Env vars:
  IG_ACCESS_TOKEN  — long-lived token from Meta developer portal
  IG_ACCOUNT_ID    — Instagram Business / Creator account ID
"""
from __future__ import annotations

import os
import time

import httpx

GRAPH_URL = "https://graph.facebook.com/v21.0"
MAX_POLLS = 30
POLL_INTERVAL = 5.0


def _env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"{key} env var not set")
    return val


def upload_reel(
    video_url: str,
    caption: str,
    *,
    access_token: str | None = None,
    account_id: str | None = None,
) -> str:
    """Upload a Reel and return the Instagram media ID."""
    token = access_token or _env("IG_ACCESS_TOKEN")
    ig_id = account_id or _env("IG_ACCOUNT_ID")

    with httpx.Client(timeout=60.0) as client:
        # Step 1: Create media container
        resp = client.post(
            f"{GRAPH_URL}/{ig_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "access_token": token,
            },
        )
        resp.raise_for_status()
        creation_id = resp.json().get("id")
        if not creation_id:
            raise RuntimeError(f"No creation_id in response: {resp.json()}")
        print(f"      IG container created (id: {creation_id})")

        # Step 2: Poll until ready
        for attempt in range(1, MAX_POLLS + 1):
            time.sleep(POLL_INTERVAL)
            poll = client.get(
                f"{GRAPH_URL}/{creation_id}",
                params={
                    "fields": "status_code",
                    "access_token": token,
                },
            )
            poll.raise_for_status()
            status = poll.json().get("status_code", "")

            if status == "FINISHED":
                print(f"      IG container ready (polled {attempt}x)")
                break
            if status == "ERROR":
                raise RuntimeError(f"IG media processing failed: {poll.json()}")
        else:
            raise RuntimeError(f"IG media not ready after {MAX_POLLS} polls")

        # Step 3: Publish
        pub = client.post(
            f"{GRAPH_URL}/{ig_id}/media_publish",
            params={
                "creation_id": creation_id,
                "access_token": token,
            },
        )
        pub.raise_for_status()
        media_id = pub.json().get("id")
        if not media_id:
            raise RuntimeError(f"No media_id in publish response: {pub.json()}")
        print(f"      IG published (media_id: {media_id})")
        return str(media_id)
