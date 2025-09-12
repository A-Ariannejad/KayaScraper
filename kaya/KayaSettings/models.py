from django.core.validators import MinValueValidator
from django.db import models
from KayaProjects.models import Job

class KayaSetting(models.Model):
    interval_minutes = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(10)],
        help_text="Polling interval in minutes (must be ≥ 10).",
    )
    jobs = models.ManyToManyField(Job, related_name="kaya_settings", blank=True)
    singleton_enforcer = models.BooleanField(default=True, unique=True, editable=False)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "KayaSetting":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={})
        return obj

    def __str__(self):
        return "Kaya Settings"