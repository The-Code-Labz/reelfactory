"""ffmpeg rendering: per-segment burn + track concat."""

import os
import subprocess


def _drawtext_escape(s):
    return (s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
             .replace("%", "\\%").replace("[", "\\[").replace("]", "\\]")
             .replace(",", "\\,").replace(";", "\\;"))


def _sub_filter(text, sub_cfg, w, h):
    size = int(sub_cfg.get("font_size") or 48)
    pos = sub_cfg.get("position") or "bottom"
    margin = int(sub_cfg.get("margin_v") or 60)
    if pos == "top":
        y = f"{margin}"
    elif pos == "center":
        y = "(h-text_h)/2"
    else:
        y = f"h-{margin}-text_h"
    return (
        f"drawtext=font='{sub_cfg.get('font', 'DejaVu Sans')}':"
        f"fontsize={size}:fontcolor={sub_cfg.get('color', 'white')}:"
        f"borderw={int(sub_cfg.get('outline') or 2)}:"
        f"bordercolor={sub_cfg.get('outline_color', 'black')}:"
        f"x=(w-text_w)/2:y={y}:text='{_drawtext_escape(text)}'"
    )


def render_segment(seg, img_path, audio_path, out_path, job_cfg, cache_dir):
    """Burn image + audio + subtitles into one segment mp4. Cached."""
    r = job_cfg["render"]
    sub = job_cfg["subtitle"]
    w, h, fps = int(r["width"]), int(r["height"]), int(r["fps"])

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path  # segment cache hit

    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
    vf += f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
    if sub.get("enabled") and seg.get("text"):
        vf += "," + _sub_filter(seg["text"], sub, w, h)

    cmd = ["ffmpeg", "-y"]
    cmd += ["-loop", "1", "-i", img_path]
    if audio_path:
        cmd += ["-i", audio_path]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
    cmd += ["-vf", vf]
    if seg.get("duration_sec") and not audio_path:
        cmd += ["-t", f"{float(seg['duration_sec']):.2f}"]
    elif not audio_path:
        cmd += ["-t", "3.0"]
    cmd += ["-c:v", r["video_codec"], "-preset", r.get("preset", "medium")]
    if r.get("crf"):
        cmd += ["-crf", str(r["crf"])]
    else:
        cmd += ["-b:v", r["video_bitrate"]]
    cmd += ["-c:a", r["audio_codec"], "-b:a", r["audio_bitrate"],
            "-pix_fmt", "yuv420p", "-shortest", out_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(out_path):
        tail = (proc.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg segment render failed: {tail}")
    return out_path


def concat_segments(seg_paths, out_path, renc_cfg):
    """Concatenate segment mp4s into the final track video."""
    if len(seg_paths) == 1:
        import shutil
        shutil.copyfile(seg_paths[0], out_path)
        return out_path

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    lst = out_path + ".concat.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in seg_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(39), chr(39)*2)}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-c", "copy", out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.unlink(lst)
    except OSError:
        pass
    if proc.returncode != 0 or not os.path.isfile(out_path):
        tail = (proc.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg concat failed: {tail}")
    return out_path
