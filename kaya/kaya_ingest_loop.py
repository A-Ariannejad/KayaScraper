# kaya_ingest_loop.py
import os
import time
import signal
import sys
import logging
from datetime import datetime
from typing import Any, Dict, List, Iterable, Set, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

# --- Django setup ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaya.settings")
import django  # noqa: E402
django.setup()

from KayaProjects.models import KayaProject, Job  # noqa: E402
from KayaSettings.models import KayaSetting
API_BASE = "https://api.kaya.ir/api/v2/projects/projects"

BASE_PARAMS = {
    "limit": 10000,      # paginate with offset below
    "fixed": "false",
    "hourly": "false",
    "hourly_min": "",
    "fixed_min": "",
    "fixed_max": "",
}

# -------- Logging setup --------
LOGGER_NAME = "kaya_ingest"
logger = logging.getLogger(LOGGER_NAME)
handler = logging.StreamHandler(sys.stdout)
fmt = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler.setFormatter(fmt)
logger.addHandler(handler)
logger.setLevel(logging.INFO)  # change to DEBUG if you want even more detail


def make_session() -> requests.Session:
    retries = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({"User-Agent": "KayaIngestLoop/1.3"})
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def load_settings() -> Tuple[int, List[int]]:
    """
    Load interval and selected skills from KayaSetting.
    - interval_minutes: enforced >= 10
    - selected skills: settings.jobs (fallback to ALL Job.external_id if none selected)
    """
    settings = KayaSetting.load()
    interval_minutes = max(10, int(settings.interval_minutes or 10))

    selected_qs = settings.jobs.all()
    if selected_qs.exists():
        skills = list(selected_qs.values_list("external_id", flat=True))
        source = "settings.jobs"
    else:
        skills = list(Job.objects.values_list("external_id", flat=True))
        source = "ALL Job.external_id (fallback)"

    logger.info(
        "Loaded settings: interval=%d min, skills_count=%d (source=%s)",
        interval_minutes, len(skills), source
    )
    if len(skills) <= 15:
        logger.info("Selected skills: %s", skills)
    else:
        logger.info("Selected skills: %s ... (total %d)", skills[:15], len(skills))

    return interval_minutes, skills


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
    page = 0
    total_for_skill = 0
    while True:
        page += 1
        batch = fetch_page(session, skill_id, offset)
        batch_count = len(batch)
        logger.debug("Skill %s | page=%d | offset=%d | batch_count=%d", skill_id, page, offset, batch_count)
        if not batch:
            break
        total_for_skill += batch_count
        for item in batch:
            yield item
        offset += batch_count
    logger.info("Skill %s | completed | total_items=%d | pages=%d", skill_id, total_for_skill, page - 1)


def ingest_once(skills: List[int]) -> int:
    """
    For each selected skill, fetch & upsert. Returns processed count.
    Uses a 'seen_project_ids' set to avoid reprocessing the same project in this run.
    """
    if not skills:
        logger.warning("No skills available to fetch. Skipping ingest cycle.")
        return 0

    start_ts = time.time()
    processed = 0
    seen: Set[int] = set()
    per_skill_counts: List[Tuple[int, int]] = []  # (skill_id, processed_count_this_skill)

    logger.info("Starting ingest cycle for %d skill(s)...", len(skills))
    with make_session() as s:
        for skill in skills:
            skill_processed_before = processed
            logger.info("Fetching for skill=%s ...", skill)
            try:
                for payload in fetch_all_for_skill(s, skill):
                    pid = payload.get("project_id")
                    if pid in seen:
                        continue
                    try:
                        KayaProject.upsert_from_payload(payload)
                        processed += 1
                        seen.add(pid)
                    except Exception as e:
                        logger.warning("Upsert failed project_id=%s (skill=%s): %s", pid, skill, e)
            except requests.HTTPError as e:
                logger.error("HTTP error on skill=%s: %s", skill, e)
            except Exception as e:
                logger.error("Unexpected error on skill=%s: %s", skill, e)

            per_skill_counts.append((skill, processed - skill_processed_before))

    dur = time.time() - start_ts
    logger.info("Ingest cycle finished: unique_projects_ingested=%d | skills=%d | duration=%.2fs",
                processed, len(skills), dur)

    # Compact per-skill summary
    if len(per_skill_counts) <= 20:
        summary = ", ".join(f"{sid}:{cnt}" for sid, cnt in per_skill_counts)
        logger.info("Per-skill new/updated counts: %s", summary)
    else:
        logger.info("Per-skill counts (first 20 shown): %s ...",
                    ", ".join(f"{sid}:{cnt}" for sid, cnt in per_skill_counts[:20]))

    return processed


def _handle_sigterm(signum, frame):
    logger.info("Received signal %s, shutting down gracefully...", signum)
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    cycle = 0
    while True:
        cycle += 1
        logger.info("=" * 72)
        logger.info("Cycle #%d | start at %s", cycle, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # Always read fresh settings BEFORE each cycle
        try:
            interval_minutes, skills = load_settings()
        except Exception as e:
            logger.error("Failed to load settings; defaulting to 10 min & all jobs. Error: %s", e)
            interval_minutes = 10
            skills = list(Job.objects.values_list("external_id", flat=True))

        try:
            ingested = ingest_once(skills)
            logger.info("[OK] Cycle #%d complete | ingested/updated %d unique projects", cycle, ingested)
        except Exception as e:
            logger.error("[ERROR] Ingest failed in cycle #%d: %s", cycle, e)

        sleep_secs = max(600, interval_minutes * 60) 
        logger.info("Cycle #%d | ended at %s", cycle, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        setting = KayaSetting.load()
        setting.last_updated = datetime.now()
        setting.save()
        logger.info("Sleeping for %d seconds (interval %d min). Next cycle will re-load settings.", sleep_secs, interval_minutes)
        time.sleep(sleep_secs)


if __name__ == "__main__":
    main()
