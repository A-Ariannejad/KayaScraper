from django.contrib import admin
from .models import KayaSetting

@admin.register(KayaSetting)
class KayaSettingAdmin(admin.ModelAdmin):
    list_display = ["interval_minutes", "selected_jobs_count"]
    filter_horizontal = ["jobs"]
    readonly_fields = [] 
    
    @admin.display(description="Selected jobs")
    def selected_jobs_count(self, obj):
        return obj.jobs.count()