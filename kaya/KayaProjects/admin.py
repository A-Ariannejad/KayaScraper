# app/admin.py
from django.contrib import admin
from django.db.models import Count
from django.db import models
from django.utils.html import format_html
from .models import KayaProject, Job


# -------- Inline / Many-to-Many helpers --------
class JobsInline(admin.TabularInline):
    model = KayaProject.jobs.through
    extra = 0
    verbose_name = "Job"
    verbose_name_plural = "Jobs"


# -------- Custom list filters --------
class BudgetPresenceFilter(admin.SimpleListFilter):
    title = "Budget"
    parameter_name = "budget_presence"

    def lookups(self, request, model_admin):
        return (
            ("with", "Has min & max"),
            ("partial", "Has one of min/max"),
            ("none", "No budget"),
        )

    def queryset(self, request, qs):
        if self.value() == "with":
            return qs.filter(budget_minimum__isnull=False, budget_maximum__isnull=False)
        if self.value() == "partial":
            return qs.filter(
                models.Q(budget_minimum__isnull=True, budget_maximum__isnull=False)
                | models.Q(budget_minimum__isnull=False, budget_maximum__isnull=True)
            )
        if self.value() == "none":
            return qs.filter(budget_minimum__isnull=True, budget_maximum__isnull=True)
        return qs


# -------- Actions --------
@admin.action(description="Mark selected as payment verified")
def mark_verified(modeladmin, request, queryset):
    queryset.update(payment_verified=True)

@admin.action(description="Mark selected as NOT payment verified")
def mark_unverified(modeladmin, request, queryset):
    queryset.update(payment_verified=False)


# -------- Admins --------
@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    search_fields = ["name", "external_id"]
    list_display = ["name", "external_id", "listings_count"]
    ordering = ["name"]
    list_per_page = 50

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_listings_count=Count("listings"))

    @admin.display(ordering="_listings_count", description="Listings")
    def listings_count(self, obj):
        return obj._listings_count


@admin.register(KayaProject)
class KayaProjectAdmin(admin.ModelAdmin):
    # List page
    list_display = [
        "title",
        "project_id",
        "submit_date",
        "is_hourly",
        "currency_code",
        "budget_range",
        "owner_country_code",
        "payment_verified",
        "freelancer_link",
    ]
    list_filter = [
        "is_hourly",
        "payment_verified",
        "currency_code",
        "owner_country_code",
        "has_attachment",
        ("jobs", admin.RelatedOnlyFieldListFilter),
        BudgetPresenceFilter,
    ]
    search_fields = [
        "title",
        "description",
        "project_id",
        "owner_country",
        "owner_city",
        "jobs__name",
    ]
    date_hierarchy = "submit_date"
    ordering = ["-submit_date"]
    list_select_related = []  # (no FK fields here, but keep for consistency)
    filter_horizontal = ["jobs"]  # nice M2M widget
    list_per_page = 50
    actions = [mark_verified, mark_unverified]

    # Detail page layout
    fieldsets = (
        ("Identity", {
            "fields": ("project_id", "submit_date", "freelancer_url"),
        }),
        ("Content", {
            "fields": ("title", "description"),
        }),
        ("Type & Budget", {
            "fields": ("is_hourly", ("budget_minimum", "budget_maximum"), "currency_code"),
        }),
        ("Owner/Location", {
            "fields": (("owner_country", "owner_country_code", "owner_city"),),
        }),
        ("Flags", {
            "fields": (("payment_verified", "has_attachment"),),
        }),
        ("Relations", {
            "fields": ("jobs",),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Prefetch jobs for faster changelist rendering with ManyToMany
        return qs.prefetch_related("jobs")

    # Niceties for columns
    @admin.display(description="Budget")
    def budget_range(self, obj):
        if obj.budget_minimum is not None and obj.budget_maximum is not None:
            return f"{obj.budget_minimum}–{obj.budget_maximum}"
        if obj.budget_minimum is not None:
            return f"≥ {obj.budget_minimum}"
        if obj.budget_maximum is not None:
            return f"≤ {obj.budget_maximum}"
        return "—"

    @admin.display(description="Freelancer")
    def freelancer_link(self, obj):
        if not obj.freelancer_url:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open</a>', obj.freelancer_url)

from django.contrib import admin
admin.site.site_header = "Kaya Admin"
admin.site.site_title = "Kaya Admin"
admin.site.index_title = "Data Ingestion & Listings"