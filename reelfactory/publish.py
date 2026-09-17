"""Publishing: local copy + webhook, secrets redacted from logs."""

import json
import os
import shutil
import urllib.request


def redact(obj):
    """Recursively redact secret-looking fields for logging."""
    SECRET_KEYS = ("api_key", "webhook_secret", "key", "token", "secret", "password", "authorization")
    if isinstance(obj, dict):
        return {k: ("REDACTED" if k.lower() in SECRET_KEYS else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def publish(job, final_path, report, log):
    pub = job.get("publish") or {}
    published = []

    local_dir = pub.get("local_dir")
    if local_dir:
        os.makedirs(local_dir, exist_ok=True)
        dest = os.path.join(local_dir, os.path.basename(final_path))
        shutil.copyfile(final_path, dest)
        published.append({"type": "local", "path": dest})
        log(f"published -> {dest}")

    hook = pub.get("webhook_url")
    if hook:
        payload = json.dumps({
            "event": "reelfactory.completed",
            "job_id": job["job_id"],
            "video": os.path.basename(final_path),
            "report": redact(report),
        }).encode()
        headers = {"Content-Type": "application/json"}
        if pub.get("webhook_secret"):
            import hmac, hashlib
            sig = hmac.new(pub["webhook_secret"].encode(), payload, hashlib.sha256).hexdigest()
            headers["X-ReelFactory-Signature"] = f"sha256={sig}"
        req = urllib.request.Request(hook, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            log(f"webhook -> {resp.status}")
        published.append({"type": "webhook", "url": hook})

    return published
