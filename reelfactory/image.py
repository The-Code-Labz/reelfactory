"""Image generation with content-hash caching and title-card fallback."""

import hashlib
import os
import subprocess
import urllib.parse
import urllib.request
import uuid


def _tmp_path(path):
    # ffmpeg infers the muxer from the extension, so keep it (e.g. foo.jpg
    # -> foo.<rand>.tmp.jpg) rather than appending ".tmp" after it.
    root, ext = os.path.splitext(path)
    return f"{root}.{uuid.uuid4().hex[:8]}.tmp{ext}"


def image_cache_key(seg, img_cfg):
    h = hashlib.sha256()
    h.update(str(img_cfg.get("provider", "none")).encode())
    h.update(str(img_cfg.get("model", "")).encode())
    h.update(str(img_cfg.get("width", "")).encode())
    h.update(str(img_cfg.get("height", "")).encode())
    h.update(str(img_cfg.get("seed", "")).encode())
    h.update(str(seg.get("image_prompt") or seg.get("text") or "")[:2000].encode())
    return h.hexdigest()[:24]


def gen_image(seg, img_cfg, cache_dir):
    """Return path to a JPEG for the segment, generating if needed.

    Falls back to a rendered title card when the provider is 'none'.
    """
    if seg.get("image_file"):
        return seg["image_file"]
    prompt = (seg.get("image_prompt") or seg.get("text") or "").strip()
    provider = img_cfg.get("provider", "none")
    w = int(img_cfg.get("width") or 1080)
    h = int(img_cfg.get("height") or 1920)

    os.makedirs(cache_dir, exist_ok=True)
    key = image_cache_key(seg, img_cfg)
    path = os.path.join(cache_dir, f"{key}.jpg")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path

    if provider == "pollinations" and prompt:
        _pollinations(prompt, img_cfg, w, h, path)
    else:
        _title_card(prompt, w, h, path)
    return path


def _pollinations(prompt, img_cfg, w, h, path):
    q = urllib.parse.urlencode({
        "width": w, "height": h,
        "model": img_cfg.get("model") or "flux",
        "nologo": "true",
    })
    if img_cfg.get("seed") is not None:
        q += "&" + urllib.parse.urlencode({"seed": img_cfg["seed"]})
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt) + "?" + q
    req = urllib.request.Request(url, headers={"User-Agent": "reelfactory/0.1"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    if len(data) < 1000:
        raise RuntimeError("pollinations returned an empty/invalid image")
    tmp = _tmp_path(path)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)


_ESCAPES = {"\\": "\\\\", ":": "\\:", "'": "\\'", "%": "\\%", "[": "\\[", "]": "\\]",
            ",": "\\,", ";": "\\;"}


def _drawtext_escape(s):
    return "".join(_ESCAPES.get(ch, ch) for ch in s)


def _title_card(text, w, h, path):
    """Render a gradient + title text card with ffmpeg lavfi."""
    import random
    from .manifest import new_job_id

    seed = random.Random(new_job_id()).randint(0, 360)
    line = _drawtext_escape((text or "ReelFactory")[:80])
    vf = (
        f"color=c=0x1a1a2e:s={w}x{h}:d=1[bg];"
        f"[bg]hue=h={seed}[h];"
        f"[h]drawtext=font='DejaVu Sans':fontsize={max(40, w // 18)}:"
        f"fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"text='{line}',format=yuvj420p"
    )
    tmp = _tmp_path(path)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", vf, "-frames:v", "1", tmp],
            capture_output=True, check=True,
        )
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)
