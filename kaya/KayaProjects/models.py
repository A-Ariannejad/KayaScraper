from __future__ import annotations
from django.db import models
from django.utils import timezone
from datetime import datetime, timezone as dt_timezone

class Job(models.Model):
    external_id = models.PositiveIntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=100, db_index=True)

    def __str__(self):
        return self.name

class KayaProject(models.Model):
    project_id = models.BigIntegerField(unique=True, db_index=True)
    submit_date = models.DateTimeField(db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    is_hourly = models.BooleanField(default=False, db_index=True)
    budget_minimum = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_maximum = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=8, db_index=True)
    has_attachment = models.BooleanField(default=False)
    payment_verified = models.BooleanField(default=False, db_index=True)
    owner_country = models.CharField(max_length=100, null=True, blank=True)
    owner_country_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    owner_city = models.CharField(max_length=100, null=True, blank=True)
    freelancer_url = models.URLField(max_length=500, null=True, blank=True)
    jobs = models.ManyToManyField(Job, related_name="listings", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    have_we_made_a_bid_on_it = models.BooleanField(default=False, db_index=True, null=True, blank=True)


    class Meta:
        indexes = [
            models.Index(fields=["is_hourly", "currency_code"]),
            models.Index(fields=["payment_verified"]),
            models.Index(fields=["submit_date"]),
        ]

    def __str__(self):
        return f"{self.title} (#{self.project_id})"
    @staticmethod
    def _ms_to_dt(ms: int) -> datetime:
        if ms and ms < 10_000_000_000:
            ms = ms * 1000
        return datetime.fromtimestamp(ms / 1000.0, tz=dt_timezone.utc)

    @classmethod
    def upsert_from_payload(cls, payload: dict) -> "KayaProject":
        submit_dt = cls._ms_to_dt(payload.get("submit_date"))
        obj, created = cls.objects.update_or_create(
            project_id=payload["project_id"],
            defaults={
                "submit_date": submit_dt,
                "title": payload.get("title") or "",
                "description": payload.get("description") or "",
                "is_hourly": bool(payload.get("is_hourly")),
                "budget_minimum": payload.get("budget_minimum"),
                "budget_maximum": payload.get("budget_maximum"),
                "currency_code": payload.get("currency_code") or "",
                "has_attachment": bool(payload.get("has_attachment")),
                "payment_verified": bool(payload.get("payment_verified")),
                "owner_country": payload.get("owner_country"),
                "owner_country_code": payload.get("owner_country_code"),
                "owner_city": payload.get("owner_city"),
                "freelancer_url": payload.get("freelancer_url"),
            },
        )
        job_objs = []
        for j in payload.get("jobs", []) or []:
            if not j:
                continue
            job, _ = Job.objects.update_or_create(
                external_id=j.get("id"),
                defaults={"name": j.get("name") or ""},
            )
            job_objs.append(job)
        if job_objs:
            obj.jobs.set(job_objs)
        else:
            obj.jobs.clear()

        return obj
