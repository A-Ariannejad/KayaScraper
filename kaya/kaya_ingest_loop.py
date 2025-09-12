# kaya_ingest_loop.py
import os
import time
import signal
import sys
from datetime import datetime
from typing import Any, Dict, List, Iterable, Set, Optional
import requests
from requests.adapters import HTTPAdapter, Retry

# --- Django setup ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaya.settings")
import django  # noqa: E402
django.setup()

from KayaProjects.models import KayaProject, Job  # noqa: E402

API_BASE = "https://api.kaya.ir/api/v2/projects/projects"

BASE_PARAMS = {
    "limit": 10000,      # paginate with offset below
    "fixed": "false",
    "hourly": "false",
    "hourly_min": "",
    "fixed_min": "",
    "fixed_max": "",
}

SLEEP_SECS = 600  # 10 minutes


def make_session() -> requests.Session:
    retries = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({"User-Agent": "KayaIngestLoop/1.2"})
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def get_skill_ids_from_db() -> List[int]:
    """All Job.external_id values from DB."""
    return list(Job.objects.values_list("external_id", flat=True))


def parse_selected_skills(argv: List[str]) -> Optional[List[int]]:
    """
    Choose skills in either way:
      1) ENV: KAYA_SKILLS='17,2037,69'
      2) CLI: python kaya_ingest_loop.py 17 2037 69
    Returns None if nothing was specified (caller will fallback to DB).
    """
    env_val = os.getenv("KAYA_SKILLS")
    if env_val:
        try:
            return [int(x.strip()) for x in env_val.split(",") if x.strip()]
        except ValueError:
            print("[WARN] Invalid KAYA_SKILLS env (must be comma-separated integers). Ignoring.")
    if len(argv) > 1:
        try:
            return [int(x) for x in argv[1:]]
        except ValueError:
            print("[WARN] Invalid CLI skills (must be integers). Ignoring.")
    return None


def fetch_page(session: requests.Session, skill_id: int, offset: int) -> List[Dict[str, Any]]:
    params = {**BASE_PARAMS, "skills": str(skill_id), "offset": offset}
    r = session.get(API_BASE, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    # API may return a bare list OR {"projects":[...]} / {"results":[...]}
    if isinstance(data, list):
        return data
    return data.get("projects") or data.get("results") or []


def fetch_all_for_skill(session: requests.Session, skill_id: int) -> Iterable[Dict[str, Any]]:
    """Iterate all pages for ONE skill id."""
    offset = 0
    while True:
        batch = fetch_page(session, skill_id, offset)
        if not batch:
            break
        for item in batch:
            yield item
        offset += len(batch)


def ingest_once(selected_skills: Optional[List[int]]) -> int:
    """
    For each selected skill, fetch & upsert. Returns processed count.
    Uses a 'seen_project_ids' set to avoid reprocessing the same project in this run.
    """
    if not selected_skills:
        skills = get_skill_ids_from_db()
        if not skills:
            print("[INFO] No skills in DB (Job.external_id). Nothing to fetch.")
            return 0
    else:
        skills = selected_skills

    processed = 0
    seen: Set[int] = set()

    with make_session() as s:
        for skill in skills:
            print(f"[INFO] Fetching skill={skill} ...")
            for payload in fetch_all_for_skill(s, skill):
                pid = payload.get("project_id")
                if pid in seen:
                    continue
                try:
                    KayaProject.upsert_from_payload(payload)
                    processed += 1
                    seen.add(pid)
                except Exception as e:
                    print(f"[WARN] Failed upsert project_id={pid} (skill={skill}): {e}", flush=True)

    return processed


def _handle_sigterm(signum, frame):
    print("\n[INFO] Received signal, shutting down gracefully...", flush=True)
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    selected = parse_selected_skills()

    while True:
        print("Last Update At:", datetime.now())
        try:
            n = ingest_once(selected)
            print(f"[OK] Ingested/updated {n} unique projects", flush=True)
        except Exception as e:
            print(f"[ERROR] Ingest failed: {e}", flush=True)
        time.sleep(SLEEP_SECS)


if __name__ == "__main__":
    main()
