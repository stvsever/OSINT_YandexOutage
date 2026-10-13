"""Shared helpers for the Yandex outage attribution pipeline.

All timestamps are handled in UTC. Raw API responses are cached on disk so the
pipeline is reproducible and polite to the free public services it relies on.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
RESEARCH = ROOT / "research"
CACHE = RAW / "_http_cache"
for p in (RAW, PROC, CACHE):
    p.mkdir(parents=True, exist_ok=True)

# Study window (UTC). The baseline ends before the first strike window opens.
STUDY_START = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
STUDY_END = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
BASELINE_END = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)

UA = "OSINT-outage-attribution-research/1.0 (academic, non-commercial; contact via repository)"

_session = requests.Session()
_session.headers.update({"User-Agent": UA})
_last_call: dict[str, float] = {}


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url: str, params: dict | None = None, *, host_key: str | None = None,
        min_interval: float = 1.0, retries: int = 6, timeout: int = 120,
        cache: bool = True, headers: dict | None = None, binary: bool = False,
        accept_status: tuple[int, ...] = (200,)):
    """GET with per-host pacing, exponential backoff and an on-disk cache."""
    key_src = url + "?" + json.dumps(params or {}, sort_keys=True)
    h = hashlib.sha1(key_src.encode()).hexdigest()
    cpath = CACHE / (h + (".bin" if binary else ".txt"))
    if cache and cpath.exists():
        return cpath.read_bytes() if binary else cpath.read_text()
    host = host_key or url.split("/")[2]
    delay = 2.0
    for attempt in range(retries):
        wait = min_interval - (time.time() - _last_call.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        try:
            r = _session.get(url, params=params, timeout=timeout, headers=headers)
        except requests.RequestException as e:  # network hiccup
            print(f"  ! {host} {type(e).__name__}, retry in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code in accept_status:
            body = r.content if binary else r.text
            if not binary and ("Maybe slow down" in body[:200] or '"error":"Timeout' in body[:200]):
                print(f"  ! {host} soft rate limit, sleeping {delay:.0f}s")
                time.sleep(delay)
                delay *= 2
                continue
            if cache:
                if binary:
                    cpath.write_bytes(body)
                else:
                    cpath.write_text(body)
            return body
        if r.status_code in (422, 429, 500, 502, 503, 504, 520, 522, 524):
            reset = r.headers.get("X-RateLimit-Reset") or r.headers.get("Retry-After")
            if r.status_code == 429 and reset and reset.replace(".", "").isdigit():
                sl = float(reset) + 1
            else:
                sl = max(delay, min_interval * 2)
            print(f"  ! {host} HTTP {r.status_code}, sleeping {sl:.0f}s")
            time.sleep(min(sl, 300))
            delay *= 2
            continue
        print(f"  ! {host} HTTP {r.status_code} for {r.url[:160]}")
        return None
    print(f"  ! giving up on {url}")
    return None


def save_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def load_json(path: Path):
    return json.loads(Path(path).read_text())
