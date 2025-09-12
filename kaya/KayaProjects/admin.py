# KayaProjects/admin.py
from django.contrib import admin
from django.db.models import Count, Q
from django.db import models
from django.utils.html import format_html
from .models import KayaProject, Job
import shlex

# ========= Generic input filter base (one-line input) =========
class InputFilter(admin.SimpleListFilter):
    template = "admin/input_filter.html"
    parameter_name = ""    # e.g. "min_budget"
    title = ""             # sidebar label
    placeholder = ""       # input placeholder

    def lookups(self, request, model_admin):
        # No dropdown choices — we render a text input instead.
        return ()

    def has_output(self):  # <-- add this
        # Force Django to show the filter even without lookup choices.
        return True

    def value(self):
        return self.used_parameters.get(self.parameter_name)

    def choices(self, changelist):
        # Provide an "All" choice so the filter section renders consistently.
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": "All",
        }


# ========= Your existing bits (unchanged) =========

class JobsInline(admin.TabularInline):
    model = KayaProject.jobs.through
    extra = 0
    verbose_name = "Job"
    verbose_name_plural = "Jobs"

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
                Q(budget_minimum__isnull=True, budget_maximum__isnull=False)
                | Q(budget_minimum__isnull=False, budget_maximum__isnull=True)
            )
        if self.value() == "none":
            return qs.filter(budget_minimum__isnull=True, budget_maximum__isnull=True)
        return qs


# ========= NEW: free-form numeric inputs for min/max =========

class MinBudgetInputFilter(InputFilter):
    title = "Min budget (≥)"
    parameter_name = "min_budget"
    placeholder = "e.g. 250"

    def queryset(self, request, qs):
        raw = self.value()
        if not raw:
            # Default behavior: treat as ≥ 0 (incl. NULL mins)
            return qs.filter(Q(budget_minimum__gte=0) | Q(budget_minimum__isnull=True))
        try:
            n = float(raw)
        except ValueError:
            return qs
        # Treat NULL min as 0; also include rows with only max present & >= n
        return qs.filter(
            Q(budget_minimum__gte=n) |
            (Q(budget_minimum__isnull=True) & Q(budget_maximum__gte=n))
        )


class MaxBudgetInputFilter(InputFilter):
    title = "Max budget (≤)"
    parameter_name = "max_budget"
    placeholder = "e.g. 1000"

    def queryset(self, request, qs):
        raw = self.value()
        if not raw:
            # Default: effectively “no cap”
            return qs
        try:
            n = float(raw)
        except ValueError:
            return qs
        # Treat NULL max as infinite; include those only if min ≤ n
        return qs.filter(
            Q(budget_maximum__lte=n) |
            (Q(budget_maximum__isnull=True) & Q(budget_minimum__lte=n))
        )


# ========= NEW: owner country dropdown built from data =========
class OwnerCountryFilter(admin.SimpleListFilter):
    title = "Owner country"
    parameter_name = "owner_country_exact"

    def lookups(self, request, model_admin):
        values = (
            KayaProject.objects
            .exclude(owner_country__isnull=True)
            .exclude(owner_country__exact="")
            .values_list("owner_country", flat=True)
            .distinct()
            .order_by("owner_country")
        )
        return tuple((v, v) for v in values)

    def queryset(self, request, qs):
        if self.value():
            return qs.filter(owner_country=self.value())
        return qs


# ========= Actions =========
@admin.action(description="Made A Bid On It")
def mark_verified(modeladmin, request, queryset):
    queryset.update(have_we_made_a_bid_on_it=True)

@admin.action(description="Remove A Bid From It")
def mark_unverified(modeladmin, request, queryset):
    queryset.update(have_we_made_a_bid_on_it=False)


# ========= Job Admin =========
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


# ========= KayaProject Admin =========
@admin.register(KayaProject)
class KayaProjectAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "project_id",
        "submit_date",
        "is_hourly",
        "currency_code",
        "budget_range",
        "owner_country_code",
        "have_we_made_a_bid_on_it",
        "freelancer_link",
    ]
    list_filter = [
        "is_hourly",
        "have_we_made_a_bid_on_it",
        "currency_code",                         # keep currency filter
        OwnerCountryFilter,                      # new owner_country filter
        "has_attachment",
        ("jobs", admin.RelatedOnlyFieldListFilter),
        BudgetPresenceFilter,                    # your presence filter
        MinBudgetInputFilter,                    # NEW: free-form min input
        MaxBudgetInputFilter,                    # NEW: free-form max input
    ]
    search_fields = [
        "title",
        "description",
        "project_id",
        "owner_country",
        "owner_city",
        "jobs__name",
    ]
    search_help_text = (
        "Tip: use `desc:` to search the description for multiple words. "
        "Example: desc: elementor responsive \"pixel perfect\" -icons"
    )
    date_hierarchy = "submit_date"
    ordering = ["-submit_date"]
    list_select_related = []
    filter_horizontal = ["jobs"]
    list_per_page = 50
    actions = [mark_verified, mark_unverified]
    readonly_fields = ("created_at", "updated_at")

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
            "fields": (("have_we_made_a_bid_on_it", "has_attachment"),),
        }),
        ("Relations", {
            "fields": ("jobs",),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("jobs")

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

    def get_search_results(self, request, queryset, search_term):
        """
        Supports: desc: multi-term search in description.
        All other terms use normal search_fields behavior.
        """
        if search_term.strip().lower().startswith("desc:"):
            raw = search_term.split(":", 1)[1].strip()
            try:
                tokens = [t for t in shlex.split(raw) if t]
            except ValueError:
                tokens = [t for t in raw.split() if t]

            must_include, must_exclude = [], []
            for t in tokens:
                if t.startswith("-") and len(t) > 1:
                    must_exclude.append(t[1:])
                else:
                    must_include.append(t)

            for t in must_include:
                queryset = queryset.filter(description__icontains=t)
            for t in must_exclude:
                queryset = queryset.exclude(description__icontains=t)

            return queryset, False

        return super().get_search_results(request, queryset, search_term)


# --- Admin branding ---
admin.site.site_header = "Kaya Admin"
admin.site.site_title = "Kaya Admin"
admin.site.index_title = "Data Ingestion & Listings"
