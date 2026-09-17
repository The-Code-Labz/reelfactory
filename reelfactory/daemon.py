"""Daemon mode: watch manifest mtime, re-run on change."""

import os
import time

POLL_SECONDS = 5


def daemon_loop(manifest_path, log=print):
    from .manifest import load_manifest, ManifestError
    from .pipeline import run_pipeline

    last_mtime = None
    log(f"daemon watching {manifest_path} (poll {POLL_SECONDS}s)")
    while True:
        try:
            mtime = os.path.getmtime(manifest_path)
        except OSError:
            time.sleep(POLL_SECONDS)
            continue
        if last_mtime is None:
            last_mtime = mtime
        elif mtime != last_mtime:
            last_mtime = mtime
            log(f"manifest changed; starting job")
            try:
                run_pipeline(load_manifest(manifest_path), log=log)
            except ManifestError as e:
                log(f"manifest invalid: {e}")
            except Exception as e:
                log(f"job failed: {e}")
        time.sleep(POLL_SECONDS)
