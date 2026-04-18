"""Upload video to a GitHub Release so it has a public URL.

Used by Instagram upload (Graph API needs a publicly accessible video URL).
Requires the `gh` CLI (pre-installed in GitHub Actions runners).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)


def upload_to_release(video_path: Path, tag: str | None = None) -> str:
    """Create (or reuse) a GitHub release, upload the MP4, return public URL."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    tag = tag or f"short-{video_path.stem}"

    # Create release (ignore error if tag already exists)
    try:
        _run([
            "gh", "release", "create", tag,
            "--title", tag,
            "--notes", "Auto-generated short video asset",
        ])
    except subprocess.CalledProcessError:
        pass  # release already exists

    # Upload asset (overwrite if exists via --clobber)
    _run([
        "gh", "release", "upload", tag,
        str(video_path),
        "--clobber",
    ])

    # Get the download URL for the uploaded asset
    result = _run([
        "gh", "release", "view", tag, "--json", "assets",
    ])
    assets = json.loads(result.stdout).get("assets", [])
    filename = video_path.name
    for asset in assets:
        if asset.get("name") == filename:
            return str(asset["url"])

    raise RuntimeError(f"Asset {filename} not found in release {tag}")


def cleanup_old_releases(keep: int = 5) -> None:
    """Delete oldest releases beyond `keep` count to save storage."""
    result = _run([
        "gh", "release", "list", "--json", "tagName", "--limit", "100",
    ])
    releases = json.loads(result.stdout)
    short_releases = [r for r in releases if r["tagName"].startswith("short-")]

    if len(short_releases) <= keep:
        return

    to_delete = short_releases[keep:]
    for rel in to_delete:
        tag = rel["tagName"]
        try:
            _run(["gh", "release", "delete", tag, "--yes", "--cleanup-tag"])
            print(f"      Cleaned up old release: {tag}")
        except subprocess.CalledProcessError:
            pass
