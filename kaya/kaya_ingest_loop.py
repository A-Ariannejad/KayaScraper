import os
import time
import signal
import sys
from typing import Any, Dict, List
import requests
from requests.adapters import HTTPAdapter, Retry
import django 
from KayaProjects.models import KayaProject 

django.setup()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaya.settings")


API_BASE = "https://api.kaya.ir/api/v2/projects/projects"
DEFAULT_PARAMS = {
    "limit": 10000,
    "offset": 0,
    "skills": 17,
    "fixed": "false",
    "hourly": "false",
    "hourly_min": "",
    "fixed_min": "",
    "fixed_max": "",
}

def make_session() -> requests.Session:
    retries = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({"User-Agent": "KayaIngestLoop/1.0"})
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

def fetch_batch(offset: int) -> List[Dict[str, Any]]:
    with make_session() as s:
        r = s.get(API_BASE, params={**DEFAULT_PARAMS, "offset": offset}, timeout=25)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("projects", []) or []

def ingest_once() -> int:
    """Fetch all pages once and upsert. Returns number of records processed."""
    total = 0
    offset = DEFAULT_PARAMS["offset"]
    while True:
        items = fetch_batch(offset)
        if not items:
            break
        for payload in items:
            try:
                KayaProject.upsert_from_payload(payload)
                total += 1
            except Exception as e:
                pid = payload.get("project_id")
                print(f"[WARN] Failed upsert project_id={pid}: {e}", flush=True)
        offset += len(items)
    return total

def _handle_sigterm(signum, frame):
    print("\n[INFO] Received signal, shutting down gracefully...", flush=True)
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    SLEEP_SECS = 600 
    while True:
        try:
            n = ingest_once()
            print(f"[OK] Ingested/updated {n} projects", flush=True)
        except Exception as e:
            print(f"[ERROR] Ingest failed: {e}", flush=True)
        time.sleep(SLEEP_SECS)

if __name__ == "__main__":
    main()
