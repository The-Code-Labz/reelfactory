"""Job manifest schema and validation."""

import json
import os
import uuid


DEFAULTS = {
    "voice": {
        "provider": "none",
        "voice": "en-US-AriaNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "model": None,
        "base_url": None,
        "api_key": None,
    },
    "subtitle": {
        "enabled": True,
        "font": "DejaVu Sans",
        "font_size": 48,
        "color": "white",
        "outline_color": "black",
        "outline": 2,
        "position": "bottom",
        "margin_v": 60,
    },
    "image": {
        "provider": "none",
        "width": 1080,
        "height": 1920,
        "seed": None,
        "model": None,
        "api_key": None,
        "style": None,
    },
    "render": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "video_codec": "libx264",
        "video_bitrate": "4M",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "preset": "medium",
        "crf": None,
    },
    "publish": {
        "local_dir": None,
        "webhook_url": None,
        "webhook_secret": None,
    },
}


class ManifestError(ValueError):
    """Raised when a job manifest is invalid."""


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def new_job_id():
    return uuid.uuid4().hex[:12]


def load_manifest(path):
    """Load, merge defaults, and validate a job manifest."""
    if not os.path.isfile(path):
        raise ManifestError(f"manifest not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest is not valid JSON: {e}")

    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be a JSON object")

    job = _deep_merge(DEFAULTS, raw)
    job.setdefault("job_id", new_job_id())
    job.setdefault("output_dir", os.path.join(os.path.dirname(os.path.abspath(path)), "output"))
    validate_manifest(job)
    return job


def validate_manifest(job):
    errs = []

    tracks = job.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errs.append("tracks: required, must be a non-empty array")
        tracks = []

    for ti, track in enumerate(tracks):
        tag = f"tracks[{ti}]"
        if not isinstance(track, dict):
            errs.append(f"{tag}: must be an object")
            continue
        if not track.get("name"):
            errs.append(f"{tag}.name: required")
        segs = track.get("segments")
        if not isinstance(segs, list) or not segs:
            errs.append(f"{tag}.segments: required, must be a non-empty array")
            continue
        for si, seg in enumerate(segs):
            stag = f"{tag}.segments[{si}]"
            if not isinstance(seg, dict):
                errs.append(f"{stag}: must be an object")
                continue
            has_text = bool(seg.get("text"))
            has_img = bool(seg.get("image_file") or seg.get("image_prompt"))
            if not has_text and not has_img:
                errs.append(f"{stag}: needs 'text' or 'image_file'/'image_prompt'")
            if seg.get("image_file"):
                p = seg["image_file"]
                if not os.path.isfile(p):
                    errs.append(f"{stag}.image_file: not found: {p}")
            d = seg.get("duration_sec")
            if d is not None:
                try:
                    d = float(d)
                    if d <= 0 or d > 600:
                        errs.append(f"{stag}.duration_sec: must be 0 < d <= 600")
                except (TypeError, ValueError):
                    errs.append(f"{stag}.duration_sec: must be a number")

    if job["voice"]["provider"] not in ("none", "edge", "openai", "elevenlabs", "fal", "azure", "custom"):
        errs.append("voice.provider: unsupported")
    if job["image"]["provider"] not in ("none", "pollinations", "local", "fal"):
        errs.append("image.provider: unsupported")
    if job["voice"]["provider"] != "none" and not job["voice"].get("voice"):
        errs.append("voice.voice: required when provider is not 'none'")
    for section, key in (("voice", "api_key"), ("voice", "base_url"),
                          ("publish", "webhook_url"), ("publish", "webhook_secret")):
        val = job.get(section, {}).get(key)
        if val is not None and not isinstance(val, str):
            errs.append(f"{section}.{key}: must be a string")

    if errs:
        raise ManifestError("manifest validation failed:\n  - " + "\n  - ".join(errs))
