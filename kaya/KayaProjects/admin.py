# KayaProjects/admin.py
from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html
from .models import KayaProject, Job
import shlex

# ---------- Base input filter (kept for potential future single-input filters) ----------
class InputFilter(admin.SimpleListFilter):
    template = "admin/input_filter.html"
    parameter_name = ""
    title = ""
    placeholder = ""

    def lookups(self, request, model_admin):
        return ()

    def has_output(self):
        return True

    def value(self):
        return self.used_parameters.get(self.parameter_name)

    def choices(self, changelist):
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": "All",
        }

# ---------- Combined min/max range filter (ONE form) ----------
class BudgetRangeFilter(admin.SimpleListFilter):
    """
    Combined min/max filter using two GET params:
      ?min_budget=<number>&max_budget=<number>

    We make parameter_name = 'min_budget' (a *real* param) so the admin
    recognizes it. We also manually "consume" both params in __init__ so
    the admin won't 302-strip them with e=1.
    """
    title = "Budget range"
    template = "admin/input_filter.html"

    # IMPORTANT: use a *real* key here
    parameter_name = "min_budget"

    # Both real keys we handle
    param_min = "min_budget"
    param_max = "max_budget"

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        self.request = request

        # --- CRITICAL: consume BOTH params so admin doesn't strip them ---
        # super() already popped self.parameter_name (min_budget), but we
        # defensively clean both to avoid a 302 with e=1.
        if self.param_min in params:
            del params[self.param_min]
        if self.param_max in params:
            del params[self.param_max]

    def lookups(self, request, model_admin):
        return ()

    def has_output(self):
        return True

    def expected_parameters(self):
        # Tell admin these are legitimate for this filter.
        return [self.param_min, self.param_max]

    # Prefill values for the inputs
    def min_value(self):
        return self.request.GET.get(self.param_min, "")

    def max_value(self):
        return self.request.GET.get(self.param_max, "")

    def choices(self, changelist):
        # "All" choice removes both params
        yield {
            "selected": (
                (self.request.GET.get(self.param_min) in (None, ""))
                and (self.request.GET.get(self.param_max) in (None, ""))
            ),
            "query_string": changelist.get_query_string(
                remove=[self.param_min, self.param_max]
            ),
            "display": "All",
        }

    def queryset(self, request, qs):
        raw_min = self.request.GET.get(self.param_min, "")
        raw_max = self.request.GET.get(self.param_max, "")

        # DEBUG: uncomment if you want to see what arrives AFTER redirect
        print("DEBUG BudgetRangeFilter queryset got:", repr(raw_min), repr(raw_max))

        if (raw_min in (None, "")) and (raw_max in (None, "")):
            return qs

        # Parse to numbers (tolerant)
        nmin = nmax = None
        try:
            if raw_min not in (None, ""):
                nmin = float(raw_min)
        except ValueError:
            pass
        try:
            if raw_max not in (None, ""):
                nmax = float(raw_max)
        except ValueError:
            pass

        cond = Q()
        if nmin is not None:
            # min ≥ nmin OR (min is NULL and max ≥ nmin)
            cond &= Q(budget_minimum__gte=nmin) | (
                Q(budget_minimum__isnull=True) & Q(budget_maximum__gte=nmin)
            )
        if nmax is not None:
            # max ≤ nmax OR (max is NULL and min ≤ nmax)
            cond &= Q(budget_maximum__lte=nmax) | (
                Q(budget_maximum__isnull=True) & Q(budget_minimum__lte=nmax)
            )

        return qs.filter(cond)
    
# ---------- Your existing filters/actions/admins (unchanged) ----------
class JobsInline(admin.TabularInline):
    model = KayaProject.jobs.through
    extra = 0
    verbose_name = "Job"
    verbose_name_plural = "Jobs"

class BudgetPresenceFilter(admin.SimpleListFilter):
    title = "Budget"
    parameter_name = "budget_presence"
    def lookups(self, request, model_admin):
        return (("with","Has min & max"),("partial","Has one of min/max"),("none","No budget"))
    def queryset(self, request, qs):
        v = self.value()
        if v == "with":
            return qs.filter(budget_minimum__isnull=False, budget_maximum__isnull=False)
        if v == "partial":
            return qs.filter(Q(budget_minimum__isnull=True, budget_maximum__isnull=False) | Q(budget_minimum__isnull=False, budget_maximum__isnull=True))
        if v == "none":
            return qs.filter(budget_minimum__isnull=True, budget_maximum__isnull=True)
        return qs

class OwnerCountryFilter(admin.SimpleListFilter):
    title = "Owner country"
    parameter_name = "owner_country_exact"
    def lookups(self, request, model_admin):
        values = (KayaProject.objects.exclude(owner_country__isnull=True)
                  .exclude(owner_country__exact="")
                  .values_list("owner_country", flat=True)
                  .distinct().order_by("owner_country"))
        return tuple((v, v) for v in values)
    def queryset(self, request, qs):
        if self.value():
            return qs.filter(owner_country=self.value())
        return qs

@admin.action(description="Made A Bid On It")
def mark_verified(modeladmin, request, queryset):
    queryset.update(have_we_made_a_bid_on_it=True)
@admin.action(description="Remove A Bid From It")
def mark_unverified(modeladmin, request, queryset):
    queryset.update(have_we_made_a_bid_on_it=False)

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    search_fields = ["name", "external_id"]
    list_display = ["name", "external_id", "listings_count"]
    ordering = ["name"]
    list_per_page = 50
    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_listings_count=Count("listings"))
    @admin.display(ordering="_listings_count", description="Listings")
    def listings_count(self, obj):
        return obj._listings_count

@admin.register(KayaProject)
class KayaProjectAdmin(admin.ModelAdmin):
    list_display = [
        "title","project_id","submit_date","is_hourly","currency_code",
        "budget_range","owner_country_code","have_we_made_a_bid_on_it","freelancer_link",
    ]
    list_filter = [
        "is_hourly",
        "have_we_made_a_bid_on_it",
        "currency_code",
        OwnerCountryFilter,
        "has_attachment",
        ("jobs", admin.RelatedOnlyFieldListFilter),
        BudgetPresenceFilter,
        BudgetRangeFilter,   # <-- use the combined one
    ]
    search_fields = ["title","description","project_id","owner_country","owner_city","jobs__name"]
    search_help_text = (
        "Tip: use `desc:` to search the description for multiple words. "
        "Example: desc: elementor responsive \"pixel perfect\" -icons"
    )
    date_hierarchy = "submit_date"
    ordering = ["-submit_date"]
    filter_horizontal = ["jobs"]
    list_per_page = 50
    actions = [mark_verified, mark_unverified]
    readonly_fields = ("created_at","updated_at")
    fieldsets = (
        ("Identity", {"fields": ("project_id","submit_date","freelancer_url")}),
        ("Content", {"fields": ("title","description")}),
        ("Type & Budget", {"fields": ("is_hourly",("budget_minimum","budget_maximum"),"currency_code")}),
        ("Owner/Location", {"fields": (("owner_country","owner_country_code","owner_city"),)}),
        ("Flags", {"fields": (("have_we_made_a_bid_on_it","has_attachment"),)}),
        ("Relations", {"fields": ("jobs",)}),
        ("Timestamps", {"classes": ("collapse",), "fields": ("created_at","updated_at")}),
    )
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("jobs")
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
        return "—" if not obj.freelancer_url else format_html('<a href="{}" target="_blank" rel="noopener">Open</a>', obj.freelancer_url)
    def get_search_results(self, request, queryset, search_term):
        if search_term.strip().lower().startswith("desc:"):
            raw = search_term.split(":", 1)[1].strip()
            try:
                tokens = [t for t in shlex.split(raw) if t]
            except ValueError:
                tokens = [t for t in raw.split() if t]
            must_include, must_exclude = [], []
            for t in tokens:
                (must_exclude if t.startswith("-") and len(t) > 1 else must_include).append(t[1:] if t.startswith("-") else t)
            for t in must_include:
                queryset = queryset.filter(description__icontains=t)
            for t in must_exclude:
                queryset = queryset.exclude(description__icontains=t)
            return queryset, False
        return super().get_search_results(request, queryset, search_term)
