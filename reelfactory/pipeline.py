"""Pipeline: worker pool, retry, caching, report/state."""

import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from .image import gen_image
from .publish import publish, redact
from .render import concat_segments, render_segment
from .tts import gen_tts

RETRY_DELAYS = [1, 2, 4]  # seconds, exponential backoff
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


def with_retry(fn, log, what):
    delay = RETRY_DELAYS[0]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == MAX_ATTEMPTS:
                raise
            log(f"{what}: attempt {attempt} failed ({e}); retrying in {delay}s")
            time.sleep(delay)
            delay *= 2


def _dirs(job):
    base = job["output_dir"]
    rf = os.path.join(base, ".reelfactory")
    for d in (rf, os.path.join(rf, "cache", "tts"),
              os.path.join(rf, "cache", "image"),
              os.path.join(rf, "cache", "segment"),
              os.path.join(rf, "tmp")):
        os.makedirs(d, exist_ok=True)
    os.chmod(rf, 0o700)
    return rf


def _load_state(rf):
    p = os.path.join(rf, "state.json")
    if os.path.isfile(p):
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle", "tracks": {}, "updated_at": None}


def _save_state(rf, state):
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = os.path.join(rf, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, os.path.join(rf, "state.json"))


def run_pipeline(job, log=print, max_workers=None):
    rf = _dirs(job)
    state = _load_state(rf)
    state["status"] = "running"
    _save_state(rf, state)

    report = {"job_id": job["job_id"], "started_at": state["updated_at"],
              "tracks": [], "redacted_config": redact(job)}
    tmp = os.path.join(rf, "tmp")
    results = {}

    def work(ti, si, track, seg):
        tag = f"t{ti}s{si}"
        audio = with_retry(
            lambda: gen_tts(seg, job["voice"], os.path.join(rf, "cache", "tts")),
            log, f"{tag} tts")
        img = with_retry(
            lambda: gen_image(seg, job["image"], os.path.join(rf, "cache", "image")),
            log, f"{tag} image")
        out = os.path.join(tmp, f"seg_{tag}.mp4")
        with_retry(
            lambda: render_segment(seg, img, audio, out, job,
                                   os.path.join(rf, "cache", "segment")),
            log, f"{tag} render")
        return ti, si, out

    total = sum(len(t.get("segments", [])) for t in job["tracks"])
    done = 0
    workers = max_workers or min(4, max(1, (os.cpu_count() or 2)))
    log(f"job {job['job_id']}: {total} segments across {len(job['tracks'])} track(s), {workers} workers")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = []
        for ti, track in enumerate(job["tracks"]):
            for si, seg in enumerate(track["segments"]):
                futs.append(ex.submit(work, ti, si, track, seg))
        for fut in as_completed(futs):
            ti, si, out = fut.result()
            results[(ti, si)] = out
            done += 1
            log(f"segment {done}/{total} done (t{ti}s{si})")

    for ti, track in enumerate(job["tracks"]):
        segs = track["segments"]
        paths = [results[(ti, si)] for si in range(len(segs))]
        final = os.path.join(job["output_dir"], f"final_{job['job_id']}_{track['name']}.mp4")
        with_retry(lambda: concat_segments(paths, final, job["render"]), log, f"track {track['name']} concat")
        entry = {"track": track["name"], "segments": len(segs), "output": final}
        report["tracks"].append(entry)
        published = publish(job, final, report, log)
        if published:
            entry["published"] = published
        state.setdefault("tracks", {})[track["name"]] = {"status": "done", "output": final}
        log(f"track '{track['name']}' complete -> {final}")

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(rf, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    state["status"] = "done"
    _save_state(rf, state)
    log(f"job {job['job_id']} finished; report at {os.path.join(rf, 'report.json')}")
    return report
