#!/usr/bin/env python3
"""Fetch and segment YouTube transcripts for summarize-youtube skill."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BOOTSTRAP_ENV = "YT_SUMMARY_BOOTSTRAPPED"
CACHE_ROOT = Path.home() / ".cache" / "yt-summary"
VENV_DIR = CACHE_ROOT / ".venv"
DEPS_STAMP = CACHE_ROOT / ".deps_installed"
SEGMENT_SECONDS = 10 * 60
OVERLAP_SECONDS = 60
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def extract_video_id(url_or_id: str) -> str | None:
    candidate = url_or_id.strip()
    if VIDEO_ID_PATTERN.fullmatch(candidate):
        return candidate

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower().split(":")[0]
    if host in {"youtu.be", "www.youtu.be"}:
        path_candidate = parsed.path.strip("/").split("/")[0]
        return path_candidate if VIDEO_ID_PATTERN.fullmatch(path_candidate) else None

    youtube_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }
    if host not in youtube_hosts:
        return None

    if parsed.path == "/watch":
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        return query_id if VIDEO_ID_PATTERN.fullmatch(query_id) else None

    for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
        if parsed.path.startswith(prefix):
            path_candidate = parsed.path[len(prefix) :].split("/")[0]
            return path_candidate if VIDEO_ID_PATTERN.fullmatch(path_candidate) else None

    return None


def canonical_video_url(video_id: str) -> str:
    return f"https://youtube.com/watch?v={video_id}"


def in_bootstrap_venv() -> bool:
    executable = Path(sys.executable).resolve()
    venv_root = VENV_DIR.resolve()
    try:
        executable.relative_to(venv_root)
        return True
    except ValueError:
        return False


def ensure_bootstrap() -> None:
    if os.environ.get(BOOTSTRAP_ENV) == "1":
        return
    if in_bootstrap_venv():
        return

    python_path = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    needs_venv = not python_path.exists()
    needs_install = needs_venv or not DEPS_STAMP.exists()

    try:
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        if needs_venv:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        if needs_install:
            subprocess.check_call(
                [
                    str(python_path),
                    "-m",
                    "pip",
                    "install",
                    "youtube-transcript-api",
                    "httpx",
                ]
            )
            DEPS_STAMP.write_text("youtube-transcript-api,httpx\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError) as exc:
        eprint("Failed to bootstrap dependencies for yt-summary.")
        eprint("Next steps:")
        eprint("1) Ensure Python can create virtual environments (`python -m venv`).")
        eprint("2) Ensure internet access for pip package installation.")
        eprint(f"Debug details: {exc}")
        raise SystemExit(1) from exc

    env = os.environ.copy()
    env[BOOTSTRAP_ENV] = "1"
    os.execve(
        str(python_path),
        [str(python_path), str(Path(__file__).resolve()), *sys.argv[1:]],
        env,
    )


def normalize_transcript_rows(rows: list[object]) -> list[dict[str, float | str]]:
    normalized: list[dict[str, float | str]] = []
    for row in rows:
        text = ""
        start = 0.0
        duration = 0.0
        if isinstance(row, dict):
            text = str(row.get("text", "")).strip()
            start = float(row.get("start", 0.0) or 0.0)
            duration = float(row.get("duration", 0.0) or 0.0)
        else:
            text = str(getattr(row, "text", "")).strip()
            start = float(getattr(row, "start", 0.0) or 0.0)
            duration = float(getattr(row, "duration", 0.0) or 0.0)

        if not text:
            continue
        normalized.append(
            {
                "text": text.replace("\n", " ").strip(),
                "start": max(start, 0.0),
                "duration": max(duration, 0.0),
            }
        )
    normalized.sort(key=lambda item: float(item["start"]))
    return normalized


def fetch_with_youtube_transcript_api(
    video_id: str, language: str
) -> tuple[list[dict[str, float | str]], str]:
    from youtube_transcript_api import YouTubeTranscriptApi

    rows: object
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        rows = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
    else:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=[language])
        rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)

    if not isinstance(rows, list):
        raise RuntimeError("youtube-transcript-api returned unexpected payload")

    transcript = normalize_transcript_rows(rows)
    if not transcript:
        raise RuntimeError("youtube-transcript-api returned an empty transcript")
    return transcript, language


def fetch_with_transcript_api(
    video_id: str, language: str, api_key: str
) -> tuple[list[dict[str, float | str]], str]:
    import httpx

    base_url = os.getenv("TRANSCRIPT_API_BASE_URL", "https://transcriptapi.com/api/v2")
    endpoint = base_url.rstrip("/") + "/youtube/transcript"
    response = httpx.get(
        endpoint,
        params={"video_url": video_id, "language": language},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    if response.status_code >= 400:
        body_preview = response.text.strip().replace("\n", " ")[:200]
        raise RuntimeError(f"TranscriptAPI HTTP {response.status_code}: {body_preview}")

    payload = response.json()
    transcript_rows: object = None
    detected_language = language
    if isinstance(payload, dict):
        if isinstance(payload.get("transcript"), list):
            transcript_rows = payload.get("transcript")
        elif isinstance(payload.get("data"), dict):
            nested = payload.get("data")
            if isinstance(nested, dict) and isinstance(nested.get("transcript"), list):
                transcript_rows = nested.get("transcript")
        if isinstance(payload.get("language"), str):
            detected_language = payload["language"]

    if not isinstance(transcript_rows, list):
        raise RuntimeError("TranscriptAPI response did not include transcript data")

    transcript = normalize_transcript_rows(transcript_rows)
    if not transcript:
        raise RuntimeError("TranscriptAPI returned an empty transcript")
    return transcript, detected_language


def fetch_transcript(
    video_id: str, language: str
) -> tuple[list[dict[str, float | str]], str, str]:
    errors: list[str] = []
    try:
        transcript, detected_language = fetch_with_youtube_transcript_api(video_id, language)
        return transcript, detected_language, "youtube-transcript-api"
    except Exception as exc:
        errors.append(f"youtube-transcript-api failed: {exc}")

    api_key = os.getenv("TRANSCRIPT_API_KEY", "").strip()
    if api_key:
        try:
            transcript, detected_language = fetch_with_transcript_api(video_id, language, api_key)
            return transcript, detected_language, "TranscriptAPI"
        except Exception as exc:
            errors.append(f"TranscriptAPI failed: {exc}")

    joined_errors = " | ".join(errors) if errors else "No transcript provider returned data."
    raise RuntimeError(joined_errors)


def fetch_video_metadata(video_url: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                video_url,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {}

    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def format_hhmmss(total_seconds: float) -> str:
    seconds = max(int(round(total_seconds)), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def format_segment_time(total_seconds: float) -> str:
    seconds = max(int(total_seconds), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def build_segments(
    transcript: list[dict[str, float | str]],
    segment_seconds: int = SEGMENT_SECONDS,
    overlap_seconds: int = OVERLAP_SECONDS,
) -> list[dict[str, object]]:
    if not transcript:
        return []
    step = segment_seconds - overlap_seconds
    if step <= 0:
        raise ValueError("overlap must be less than segment duration")

    last_second = max(
        float(item["start"]) + float(item.get("duration", 0.0) or 0.0) for item in transcript
    )
    start = 0.0
    segments: list[dict[str, object]] = []
    index = 1

    while start <= last_second:
        end = start + float(segment_seconds)
        lines = [
            row
            for row in transcript
            if start <= float(row["start"]) < end
        ]
        if lines:
            segments.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "lines": lines,
                }
            )
            index += 1
        start += float(step)

    if not segments:
        segments.append(
            {
                "index": 1,
                "start": 0.0,
                "end": float(segment_seconds),
                "lines": transcript,
            }
        )
    return segments


def write_segments(temp_dir: Path, segments: list[dict[str, object]]) -> list[Path]:
    written_paths: list[Path] = []
    for segment in segments:
        index = int(segment["index"])
        start = float(segment["start"])
        end = float(segment["end"])
        lines = segment["lines"]

        if not isinstance(lines, list):
            raise ValueError("segment lines payload is invalid")

        file_path = temp_dir / f"segment_{index:03d}.md"
        header = (
            f"# Segment {index} \u2014 {format_segment_time(start)} to "
            f"{format_segment_time(end)}\n\n"
        )
        body_lines: list[str] = []
        for row in lines:
            if not isinstance(row, dict):
                continue
            body_lines.append(
                f"[{format_segment_time(float(row['start']))}] {str(row['text']).strip()}\n"
            )
        file_path.write_text(header + "".join(body_lines), encoding="utf-8")
        written_paths.append(file_path)

    return written_paths


def estimate_duration_seconds(transcript: list[dict[str, float | str]]) -> float:
    if not transcript:
        return 0.0
    return max(float(row["start"]) + float(row.get("duration", 0.0) or 0.0) for row in transcript)


def build_meta(
    video_id: str,
    url: str,
    language: str,
    transcript: list[dict[str, float | str]],
    segment_count: int,
    metadata: dict[str, object],
) -> dict[str, object]:
    duration_value = metadata.get("duration")
    if isinstance(duration_value, (int, float)):
        duration = format_hhmmss(float(duration_value))
    else:
        duration = format_hhmmss(estimate_duration_seconds(transcript))

    title = metadata.get("title")
    channel = metadata.get("channel") or metadata.get("uploader")
    return {
        "video_id": video_id,
        "title": str(title) if title else f"YouTube video {video_id}",
        "channel": str(channel) if channel else "Unknown channel",
        "duration": duration,
        "url": url,
        "segment_count": segment_count,
        "language": language,
    }


def prepare_temp_dir(video_id: str) -> Path:
    root = Path(tempfile.gettempdir()) / f"yt-summary-{video_id}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch and segment YouTube transcript")
    p.add_argument("url_or_id", nargs="?", help="YouTube URL or 11-character video ID")
    p.add_argument("--lang", default="en", help="Preferred transcript language (default: en)")
    p.add_argument(
        "--check-setup",
        action="store_true",
        help="Print setup status JSON and exit 0",
    )
    return p


def setup_status() -> dict[str, bool]:
    python_path = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv_exists = python_path.exists()
    deps_installed = venv_exists and DEPS_STAMP.exists()
    transcript_api_key_set = bool(os.getenv("TRANSCRIPT_API_KEY", "").strip())
    yt_dlp_available = shutil.which("yt-dlp") is not None
    return {
        "venv_exists": venv_exists,
        "deps_installed": deps_installed,
        "transcript_api_key_set": transcript_api_key_set,
        "yt_dlp_available": yt_dlp_available,
    }


def main(argv: list[str] | None = None) -> int:
    arg_parser = parser()
    args = arg_parser.parse_args(argv)

    if args.check_setup:
        try:
            print(json.dumps(setup_status()))
        except Exception:
            print(
                json.dumps(
                    {
                        "venv_exists": False,
                        "deps_installed": False,
                        "transcript_api_key_set": False,
                        "yt_dlp_available": False,
                    }
                )
            )
        return 0

    if not args.url_or_id:
        arg_parser.error("the following arguments are required: url_or_id")

    video_id = extract_video_id(args.url_or_id)
    if not video_id:
        eprint("Invalid YouTube URL or video ID.")
        eprint("Expected an 11-character video ID or a valid YouTube URL.")
        eprint("Example: https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return 2

    ensure_bootstrap()

    try:
        transcript, detected_language, _source = fetch_transcript(video_id, args.lang)
    except Exception as exc:
        api_key = os.getenv("TRANSCRIPT_API_KEY", "").strip()
        eprint(f"Failed to fetch transcript for video '{video_id}'.")
        if api_key:
            eprint("TRANSCRIPT_API_KEY is set, but transcript providers still failed.")
            eprint("Next steps:")
            eprint("1) Verify your TranscriptAPI key and remaining credits.")
            eprint("2) Try a different video or language with --lang.")
            eprint("3) Check if the video has subtitles enabled.")
        else:
            eprint("YouTube may be blocking this IP for transcript scraping.")
            eprint("Next steps:")
            eprint("1) Set TRANSCRIPT_API_KEY for reliable fallback access.")
            eprint("2) Get 100 free credits at https://transcriptapi.com")
            eprint("3) Retry with: TRANSCRIPT_API_KEY=... python prepare.py <url>")
        eprint(f"Debug details: {exc}")
        return 1

    if not transcript:
        eprint("Transcript fetch returned no usable text.")
        eprint("Try a different language: --lang en")
        return 1

    url = canonical_video_url(video_id)
    metadata = fetch_video_metadata(url)
    segments = build_segments(transcript)
    temp_dir = prepare_temp_dir(video_id)
    segment_files = write_segments(temp_dir, segments)
    meta = build_meta(
        video_id=video_id,
        url=url,
        language=detected_language or args.lang,
        transcript=transcript,
        segment_count=len(segment_files),
        metadata=metadata,
    )
    (temp_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(str(temp_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
