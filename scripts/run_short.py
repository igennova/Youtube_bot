#!/usr/bin/env python3
"""
Fully automated YouTube Short pipeline.

  Groq → ONE full narration + image prompts
  Edge TTS → ONE audio file (30-40s)
  DeAPI → images (one per ~5-7s of audio)
  Captions → SRT from narration chunks
  FFmpeg → 9:16 vertical MP4 with small bottom captions
  YouTube upload (optional)

Usage:
  .venv/bin/python scripts/run_short.py --channel ghost_stories
  .venv/bin/python scripts/run_short.py --channel ghost_stories --topic "abandoned hospital" --upload
  .venv/bin/python scripts/run_short.py --channel ghost_stories --upload --instagram
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "scripts" / ".env")

from pipeline.captions import build_srt
from pipeline.channel_presets import get_preset, list_channel_ids
from pipeline.edge_tts_synth import synthesize_full
from pipeline.groq_script import generate_short_pack
from pipeline.images import DEFAULT_NEGATIVE, STYLE_SUFFIX, full_visual_prompt, save_scene_image
from pipeline.render_short import render_vertical_short
from pipeline.story_history import save_title


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate & optionally upload a YouTube Short.")
    ap.add_argument("--channel", required=True, choices=list_channel_ids())
    ap.add_argument("--topic", default="", help="Optional topic hint for Groq.")
    ap.add_argument("--upload", action="store_true", help="Upload to YouTube after render.")
    ap.add_argument("--instagram", action="store_true", help="Also post as Instagram Reel.")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = ap.parse_args()

    preset = get_preset(args.channel)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / "output" / "runs" / f"{args.channel}_{ts}"
    img_dir = run_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Script via Groq ───────────────────────────────────────────
    print("① Groq: generating script…")
    pack = generate_short_pack(
        preset, topic_hint=args.topic or None, channel_id=args.channel,
    )
    (run_dir / "script.json").write_text(json.dumps(pack, indent=2), encoding="utf-8")

    title = pack["youtube_title"]
    narration = pack["full_narration"]
    image_prompts = pack["image_prompts"]
    word_count = len(narration.split())
    print(f"   Title: {title}")
    print(f"   Narration: {word_count} words, {len(image_prompts)} image prompts")

    # ── 2. Edge TTS — ONE full audio ─────────────────────────────────
    audio_path = run_dir / "voiceover.mp3"
    print("② Edge TTS: full narration…")
    total_dur, sentence_timings = synthesize_full(narration, audio_path)
    print(f"   Audio: {total_dur:.1f}s ({len(sentence_timings)} sentences tracked)")
    if total_dur > 55:
        print(f"   ⚠ Audio is {total_dur:.0f}s — target is 30-45s")
    if total_dur < 25:
        print(f"   ⚠ Audio is {total_dur:.0f}s — might be too short")

    # ── 3. Images via DeAPI ──────────────────────────────────────────
    w = int(os.environ.get("DEAPI_IMAGE_WIDTH", "768"))
    h = int(os.environ.get("DEAPI_IMAGE_HEIGHT", "768"))
    style_suffix = os.environ.get(
        "IMAGE_STYLE_SUFFIX", preset.get("image_style_suffix", STYLE_SUFFIX)
    )
    negative = os.environ.get(
        "IMAGE_NEGATIVE_PROMPT", preset.get("image_negative_prompt", DEFAULT_NEGATIVE)
    )
    cooldown = int(os.environ.get("DEAPI_COOLDOWN", "10"))

    print(f"③ Images: {len(image_prompts)} scenes ({cooldown}s cooldown)…")

    image_paths: list[Path] = []
    for i, ip in enumerate(image_prompts):
        prompt = full_visual_prompt(ip, style_suffix)
        out = img_dir / f"scene_{i + 1:02d}.png"
        st, detail = save_scene_image(i + 1, prompt, out, width=w, height=h, negative=negative)
        if st != "ok":
            raise RuntimeError(f"Image {i + 1} failed: {detail}")
        print(f"   scene {i + 1}/{len(image_prompts)}: {detail}")
        image_paths.append(out)
        if i < len(image_prompts) - 1:
            time.sleep(cooldown)

    # ── 4. Captions (from real word timestamps) ────────────────────
    print("④ Captions…")
    srt_path = run_dir / "captions.srt"
    build_srt(sentence_timings, srt_path, total_dur)

    # ── 5. FFmpeg render (9:16) ──────────────────────────────────────
    video_path = run_dir / "short.mp4"
    print("⑤ FFmpeg: rendering 1080×1920…")
    render_vertical_short(image_paths, total_dur, audio_path, srt_path, video_path)
    print(f"   → {video_path}")

    # ── 6. History ───────────────────────────────────────────────────
    save_title(args.channel, title)

    # ── 7. YouTube upload ────────────────────────────────────────────
    if args.upload:
        from pipeline.youtube_upload import upload_short

        print("⑥ YouTube: uploading…")
        vid = upload_short(
            video_path, title, pack["youtube_description"],
            privacy_status=args.privacy,
        )
        print(f"   Uploaded! https://www.youtube.com/shorts/{vid}")
    else:
        print("   (skip YouTube — pass --upload after OAuth setup)")

    # ── 8. Instagram Reel ─────────────────────────────────────────
    if args.instagram:
        from pipeline.github_hosting import cleanup_old_releases, upload_to_release
        from pipeline.instagram_upload import upload_reel

        print("⑦ Instagram: hosting video…")
        public_url = upload_to_release(video_path)
        print(f"   Public URL: {public_url}")

        caption = f"{title}\n\n{pack['youtube_description']}"
        print("   Instagram: posting Reel…")
        media_id = upload_reel(public_url, caption)
        print(f"   Posted! (media_id: {media_id})")

        cleanup_old_releases(keep=5)
    else:
        print("   (skip Instagram — pass --instagram after Meta setup)")

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
