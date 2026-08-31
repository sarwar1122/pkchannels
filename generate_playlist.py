#!/usr/bin/env python3
"""
Automated IPTV Playlist Generator for YouTube Live Streams
Scrapes live video IDs, extracts HLS manifests, and builds M3U playlists
"""

import re
import sys
import time
import random
import logging
import subprocess
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("playlist_generator.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHANNELS_FILE = Path("channels.txt")
OUTPUT_FILE = Path("live_news.m3u")
LOG_FILE = Path("playlist_generator.log")

# Realistic browser user-agent pool to rotate through
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
]

# Headers that mimic a real browser visit to avoid bot-detection
BASE_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Patterns to locate the live video ID inside raw YouTube HTML
VIDEO_ID_PATTERNS = [
    # Canonical URL meta tag  →  most reliable signal
    r'"canonical":"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"',
    # og:url meta tag
    r'<meta property="og:url" content="https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"',
    # videoId JSON field embedded in the page data
    r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
    # hlsManifestUrl – present only for live streams
    r'"hlsManifestUrl"\s*:\s*"[^"]*?([A-Za-z0-9_-]{11})[^"]*?\.m3u8"',
    # currentVideoEndpoint
    r'"currentVideoEndpoint".*?"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
    # watchEndpoint
    r'"watchEndpoint"\s*:\s*\{[^}]*"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
]

# Patterns that confirm the scraped page really is a live broadcast
LIVE_CONFIRMATION_PATTERNS = [
    r'"isLive"\s*:\s*true',
    r'"liveBroadcastDetails"',
    r'"style"\s*:\s*"LIVE"',
    r'"badge".*?"LIVE"',
    r'hlsManifestUrl',
    r'"isLiveContent"\s*:\s*true',
]

# yt-dlp extraction settings
YTDLP_TIMEOUT = 60          # seconds before giving up on one channel
MAX_RETRIES_HTTP = 3        # HTTP-level retries per channel page request
RETRY_BACKOFF = 2.0         # exponential back-off base (seconds)
INTER_CHANNEL_DELAY = (2, 5)  # random sleep range (seconds) between channels


# ---------------------------------------------------------------------------
# HTTP session factory
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    """
    Build a requests Session with automatic retries, realistic headers, and
    a randomised User-Agent to reduce the chance of bot-detection triggering.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=MAX_RETRIES_HTTP,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    session.headers.update(headers)

    return session


# ---------------------------------------------------------------------------
# Channel list parsing
# ---------------------------------------------------------------------------

def load_channels(path: Path) -> list[dict]:
    """
    Parse channels.txt and return a list of channel dicts.

    Accepted line formats:
        ChannelName|https://www.youtube.com/@handle/live
        https://www.youtube.com/@handle/live          (name derived from URL)
        # comment lines are skipped
    """
    channels: list[dict] = []

    if not path.exists():
        log.error("channels.txt not found at %s", path.resolve())
        return channels

    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "|" in line:
                parts = line.split("|", 1)
                name = parts[0].strip()
                url  = parts[1].strip()
            else:
                url  = line
                # Derive a human-readable name from the handle when absent
                match = re.search(r"@([^/]+)", url)
                name  = match.group(1).replace("-", " ").title() if match else url

            # Ensure the URL ends with /live
            if not url.endswith("/live"):
                url = url.rstrip("/") + "/live"

            channels.append({"name": name, "url": url})
            log.debug("Loaded channel: %s → %s", name, url)

    log.info("Loaded %d channel(s) from %s", len(channels), path)
    return channels


# ---------------------------------------------------------------------------
# HTML scraping helpers
# ---------------------------------------------------------------------------

def fetch_page(session: requests.Session, url: str) -> Optional[str]:
    """
    Fetch the raw HTML of a YouTube /live page with bot-evasion measures:
    - Random User-Agent per call
    - Staggered referer header
    - Short random pre-request delay
    Returns None on any failure so callers can handle it gracefully.
    """
    # Rotate User-Agent on every individual request
    session.headers["User-Agent"] = random.choice(USER_AGENTS)

    # Set a plausible Referer (as if arriving from Google search)
    session.headers["Referer"] = "https://www.google.com/"

    # Small human-like delay before firing the request
    time.sleep(random.uniform(0.5, 1.5))

    try:
        response = session.get(url, timeout=30, allow_redirects=True)

        if response.status_code == 429:
            log.warning("Rate-limited (429) for %s – backing off 30 s", url)
            time.sleep(30)
            response = session.get(url, timeout=30, allow_redirects=True)

        if response.status_code != 200:
            log.warning(
                "HTTP %d received for %s", response.status_code, url
            )
            return None

        return response.text

    except requests.exceptions.ConnectionError as exc:
        log.warning("Connection error fetching %s: %s", url, exc)
    except requests.exceptions.Timeout:
        log.warning("Timeout fetching %s", url)
    except requests.exceptions.RequestException as exc:
        log.warning("Request failed for %s: %s", url, exc)

    return None


def is_live_broadcast(html: str) -> bool:
    """
    Inspect page HTML for signals that a live broadcast is currently active.
    Returns True only when at least one confirmation pattern matches.
    """
    for pattern in LIVE_CONFIRMATION_PATTERNS:
        if re.search(pattern, html):
            return True
    return False


def extract_video_id(html: str) -> Optional[str]:
    """
    Try each VIDEO_ID_PATTERNS in order, returning the first 11-character
    video ID found.  Returns None when no ID can be located.
    """
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, html)
        if match:
            video_id = match.group(1)
            log.debug("Matched video ID %s via pattern: %s", video_id, pattern)
            return video_id
    return None


def get_live_video_id(
    session: requests.Session, channel: dict
) -> Optional[str]:
    """
    Fetch a channel's /live page and extract the active live video ID.

    Returns:
        str  – 11-character YouTube video ID if a live stream is found
        None – channel is offline or scraping failed
    """
    url  = channel["url"]
    name = channel["name"]

    log.info("Scraping: %s (%s)", name, url)
    html = fetch_page(session, url)

    if html is None:
        log.warning("[%s] Failed to fetch page HTML", name)
        return None

    if not is_live_broadcast(html):
        log.info("[%s] No active live broadcast detected", name)
        return None

    video_id = extract_video_id(html)
    if video_id:
        log.info("[%s] Live video ID found: %s", name, video_id)
    else:
        log.warning("[%s] Live signal present but could not extract video ID", name)

    return video_id


# ---------------------------------------------------------------------------
# HLS manifest extraction via yt-dlp
# ---------------------------------------------------------------------------

def extract_hls_url(video_id: str, channel_name: str) -> Optional[str]:
    """
    Invoke yt-dlp as a subprocess to extract the direct HLS manifest (.m3u8)
    URL for a given YouTube video ID.

    Using subprocess (rather than the yt-dlp Python API) gives us:
    - Clean process isolation so a crash does not kill the whole script
    - Simple stdout capture with a hard timeout
    - Compatibility with whichever yt-dlp version is installed

    yt-dlp flags used:
        --no-warnings           suppress noise on stderr
        --no-playlist           never follow into playlists
        -f "best[ext=mp4]/best" prefer mp4; fall back to best available
        --get-url               print the direct stream URL and exit
    """
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    log.info("[%s] Extracting HLS URL for %s", channel_name, watch_url)

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--format", "best[protocol=m3u8_native]/best[ext=mp4]/best",
        "--get-url",
        # Use a realistic User-Agent at the yt-dlp level too
        "--add-header",
        f"User-Agent:{random.choice(USER_AGENTS)}",
        # Limit extraction to audio+video manifests
        "--no-check-certificates",
        watch_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            log.warning(
                "[%s] yt-dlp exited with code %d: %s",
                channel_name, result.returncode, stderr[:300],
            )
            return None

        # yt-dlp may return multiple URLs (video + audio); keep the first .m3u8
        urls = [line.strip() for line in stdout.splitlines() if line.strip()]

        for candidate in urls:
            if ".m3u8" in candidate:
                log.info("[%s] HLS URL acquired (m3u8)", channel_name)
                return candidate

        # Fall back to the first URL even if it is not an m3u8
        if urls:
            log.info(
                "[%s] No .m3u8 found; using first URL returned by yt-dlp",
                channel_name,
            )
            return urls[0]

        log.warning("[%s] yt-dlp returned no URLs", channel_name)
        return None

    except subprocess.TimeoutExpired:
        log.warning("[%s] yt-dlp timed out after %ds", channel_name, YTDLP_TIMEOUT)
    except FileNotFoundError:
        log.error(
            "yt-dlp binary not found – install it with: pip install yt-dlp"
        )
    except OSError as exc:
        log.error("[%s] OS error running yt-dlp: %s", channel_name, exc)

    return None


# ---------------------------------------------------------------------------
# M3U playlist builder
# ---------------------------------------------------------------------------

def build_m3u_playlist(streams: list[dict]) -> str:
    """
    Construct a standard M3U playlist string from a list of stream dicts.

    Each dict must contain:
        name      – human-readable channel name
        stream_url – direct HLS manifest URL
        video_id  – YouTube video ID (used to construct tvg-id)

    The #EXTM3U header carries a timestamp so apps can see when it was
    last refreshed without inspecting Git history.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f'#EXTM3U x-tvg-url="" playlist-type=VOD refresh="{now_utc}"',
        f"# Generated automatically – last updated: {now_utc}",
        f"# Total live streams: {len(streams)}",
        "",
    ]

    for entry in streams:
        name       = entry["name"]
        stream_url = entry["stream_url"]
        video_id   = entry.get("video_id", "unknown")
        tvg_id     = re.sub(r"\W+", "_", name).lower()

        lines += [
            (
                f'#EXTINF:-1 tvg-id="{tvg_id}" '
                f'tvg-name="{name}" '
                f'tvg-logo="https://img.youtube.com/vi/{video_id}/mqdefault.jpg" '
                f'group-title="Live News",'
                f"{name}"
            ),
            stream_url,
            "",          # blank line between entries improves readability
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Status / summary helpers
# ---------------------------------------------------------------------------

def write_status_json(
    total: int,
    success: int,
    offline: int,
    failed: int,
    streams: list[dict],
) -> None:
    """Write a machine-readable status file alongside the playlist."""
    now_utc = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now_utc,
        "total_channels": total,
        "live_streams": success,
        "offline_channels": offline,
        "failed_channels": failed,
        "streams": [
            {
                "name": s["name"],
                "video_id": s.get("video_id"),
                "video_url": f"https://www.youtube.com/watch?v={s.get('video_id')}",
            }
            for s in streams
        ],
    }
    status_path = Path("playlist_status.json")
    status_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Status written to %s", status_path)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Main entry point.

    Exit codes:
        0  – playlist generated successfully (≥1 live stream found)
        1  – no live streams found (all channels offline/failed)
        2  – configuration or fatal error
    """
    log.info("=" * 60)
    log.info("IPTV Playlist Generator – starting run")
    log.info("=" * 60)

    channels = load_channels(CHANNELS_FILE)
    if not channels:
        log.error("No channels loaded – aborting")
        return 2

    session = build_session()

    successful_streams: list[dict] = []
    offline_count  = 0
    failed_count   = 0

    for idx, channel in enumerate(channels, start=1):
        log.info("-" * 50)
        log.info(
            "Processing channel %d/%d: %s", idx, len(channels), channel["name"]
        )

        # ── Step 1: Scrape video ID ──────────────────────────────────────
        video_id = get_live_video_id(session, channel)

        if video_id is None:
            offline_count += 1
            log.info("[%s] Skipping – channel offline or scrape failed", channel["name"])
        else:
            # ── Step 2: Extract HLS URL via yt-dlp ──────────────────────
            hls_url = extract_hls_url(video_id, channel["name"])

            if hls_url:
                successful_streams.append(
                    {
                        "name": channel["name"],
                        "video_id": video_id,
                        "stream_url": hls_url,
                    }
                )
                log.info("[%s] ✓ Stream ready", channel["name"])
            else:
                failed_count += 1
                log.warning(
                    "[%s] ✗ Could not extract HLS URL despite live video ID",
                    channel["name"],
                )

        # Polite inter-channel delay to avoid hammering YouTube
        if idx < len(channels):
            delay = random.uniform(*INTER_CHANNEL_DELAY)
            log.debug("Sleeping %.1f s before next channel", delay)
            time.sleep(delay)

    # ── Step 3: Write playlist ───────────────────────────────────────────
    log.info("=" * 60)
    log.info(
        "Run complete – live: %d | offline: %d | failed: %d",
        len(successful_streams), offline_count, failed_count,
    )

    if successful_streams:
        playlist_content = build_m3u_playlist(successful_streams)
        OUTPUT_FILE.write_text(playlist_content, encoding="utf-8")
        log.info(
            "Playlist written to %s (%d stream(s))",
            OUTPUT_FILE, len(successful_streams),
        )
        write_status_json(
            total   = len(channels),
            success = len(successful_streams),
            offline = offline_count,
            failed  = failed_count,
            streams = successful_streams,
        )
        return 0
    else:
        log.warning("No live streams found – playlist not updated")
        # Write an empty-but-valid placeholder so the file always exists
        OUTPUT_FILE.write_text(
            "#EXTM3U\n# No live streams available at this time\n",
            encoding="utf-8",
        )
        write_status_json(
            total   = len(channels),
            success = 0,
            offline = offline_count,
            failed  = failed_count,
            streams = [],
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
