"""TTS generation with content-hash caching."""

import hashlib
import os
import subprocess

from .manifest import ManifestError


def tts_cache_key(seg, voice_cfg):
    h = hashlib.sha256()
    h.update(str(voice_cfg.get("provider", "none")).encode())
    h.update(str(voice_cfg.get("voice", "")).encode())
    h.update(str(voice_cfg.get("rate", "")).encode())
    h.update(str(voice_cfg.get("pitch", "")).encode())
    h.update(str(voice_cfg.get("model", "")).encode())
    h.update(str(seg.get("text", "")[:4000]).encode())
    return h.hexdigest()[:24]


def gen_tts(seg, voice_cfg, cache_dir):
    """Return path to an mp3 for the segment text, or None when muted.

    Caches by content hash so identical text/voice/rate/pitch reuses audio.
    """
    text = (seg.get("text") or "").strip()
    if not text:
        return None
    provider = voice_cfg.get("provider", "none")

    os.makedirs(cache_dir, exist_ok=True)
    key = tts_cache_key(seg, voice_cfg)
    path = os.path.join(cache_dir, f"{key}.mp3")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path

    if provider == "none":
        return _silence(seg, path)
    if provider == "edge":
        return _edge(text, voice_cfg, path)
    if provider == "custom":
        return _custom(text, voice_cfg, path)
    raise ManifestError(f"voice.provider '{provider}' not available in this build")


def _probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _silence(seg, path):
    dur = seg.get("duration_sec") or 3.0
    try:
        dur = float(dur)
    except (TypeError, ValueError):
        dur = 3.0
    dur = max(0.5, min(dur, 600.0))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", f"{dur:.2f}", "-c:a", "libmp3lame", path],
        capture_output=True, check=True,
    )
    return path


def _edge(text, voice_cfg, path):
    import asyncio
    import edge_tts

    async def _gen():
        comm = edge_tts.Communicate(
            text,
            voice=voice_cfg.get("voice", "en-US-AriaNeural"),
            rate=voice_cfg.get("rate", "+0%"),
            pitch=voice_cfg.get("pitch", "+0Hz"),
        )
        await comm.save(path)

    asyncio.run(_gen())
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError("edge-tts produced no audio")
    return path


def _custom(text, voice_cfg, path):
    """Generic OpenAI-compatible TTS endpoint."""
    import urllib.request

    base = (voice_cfg.get("base_url") or "").rstrip("/")
    key = voice_cfg.get("api_key")
    if not base or not key:
        raise ManifestError("custom voice provider requires base_url + api_key")
    import json as _json
    req = urllib.request.Request(
        base + "/audio/speech",
        data=_json.dumps({
            "model": voice_cfg.get("model") or "tts-1",
            "voice": voice_cfg.get("voice") or "alloy",
            "input": text,
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(path, "wb") as f:
            f.write(resp.read())
    if os.path.getsize(path) == 0:
        raise RuntimeError("custom TTS returned empty audio")
    return path
