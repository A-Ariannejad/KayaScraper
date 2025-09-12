import os
import django
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaya.settings") 
django.setup()

from KayaProjects.models import Job

def import_jobs():
    json_path = "jobs.json"
    
    if not os.path.exists(json_path):
        print(f"[ERROR] jobs.json not found at: {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to parse JSON: {e}")
            return

    items = data.get("jobs") if isinstance(data, dict) else data

    if not isinstance(items, list):
        print("[ERROR] jobs.json is not a list of job objects.")
        return

    count_created = 0
    for obj in items:
        try:
            ext_id = int(obj.get("id"))
            name = (obj.get("name") or "").strip()
            if not ext_id or not name:
                continue

            _, created = Job.objects.update_or_create(
                external_id=ext_id,
                defaults={"name": name[:100]}
            )
            if created:
                count_created += 1
        except Exception as e:
            print(f"[WARN] Skipped job {obj}: {e}")

    print(f"[DONE] Imported {count_created} new jobs.")

if __name__ == "__main__":
    import_jobs()
