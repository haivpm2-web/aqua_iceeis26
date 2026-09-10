from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django import forms
from django.db import models
from .models import (
    ExperimentRun,
    SensorSample,
    FPGAImplementation,
    EventMarker,
    ExperimentUnlockAudit,
)
from .locking import lock_run, unlock_run
from .serializers import (
    RunSerializer,
    SampleSerializer,
    ImplementationSerializer,
    EventSerializer,
)


class ResearchAdminForm(forms.ModelForm):
    """Apply the same measurement checks to staff forms and API ingestion."""

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        serializers = {
            ExperimentRun: RunSerializer,
            SensorSample: SampleSerializer,
            FPGAImplementation: ImplementationSerializer,
            EventMarker: EventSerializer,
        }
        payload = {}
        for field in self._meta.model._meta.fields:
            if field.name not in cleaned:
                continue
            value = cleaned[field.name]
            if isinstance(field, models.ForeignKey):
                value = value.pk if value else None
            if isinstance(field, models.JSONField) and value is None:
                value = {}
                cleaned[field.name] = value
            name = (
                "run_id"
                if self._meta.model is SensorSample and field.name == "run"
                else field.name
            )
            payload[name] = value
        serializer = serializers[self._meta.model](
            instance=self.instance if self.instance.pk else None, data=payload
        )
        if not serializer.is_valid():
            raise forms.ValidationError(str(serializer.errors))
        return cleaned


class EvidenceAdmin(admin.ModelAdmin):
    actions = ("delete_selected",)

    @admin.action(description="Delete selected records", permissions=["delete"])
    def delete_selected(self, request, queryset):
        from django.contrib.admin.actions import delete_selected

        try:
            with queryset._guard():
                return delete_selected(self, request, queryset)
        except ValidationError as error:
            self.message_user(request, str(error), level=messages.ERROR)

    def _locked(self, obj):
        if obj is None:
            return False
        if isinstance(obj, ExperimentRun):
            return ExperimentRun.objects.filter(pk=obj.pk, status="LOCKED").exists()
        if isinstance(obj, FPGAImplementation):
            return ExperimentRun.objects.filter(
                implementation=obj, status="LOCKED"
            ).exists()
        return ExperimentRun.objects.filter(pk=obj.run_id, status="LOCKED").exists()

    def has_change_permission(self, request, obj=None):
        return not self._locked(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._locked(obj) and super().has_delete_permission(request, obj)


class ResearchActionForm(ActionForm):
    unlock_reason = forms.CharField(
        required=False, label="Unlock reason (required for unlock)"
    )


@admin.register(ExperimentRun)
class RunAdmin(EvidenceAdmin):
    form = ResearchAdminForm
    list_display = ("id", "run_name", "run_type", "source", "status", "started_at")
    list_filter = ("source", "run_type", "status")
    readonly_fields = (
        "locked_at",
        "locked_by",
        "dataset_sha256",
        "research_package_sha256",
        "integrity_generated_at",
    )
    actions = ("delete_selected", "lock_experiments", "unlock_experiments")
    action_form = ResearchActionForm

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("unlock_experiments", None)
        return actions

    @admin.action(
        description="Lock selected COMPLETED experiments and generate integrity hashes"
    )
    def lock_experiments(self, request, queryset):
        try:
            with transaction.atomic():
                count = 0
                for run_id in queryset.order_by("pk").values_list("pk", flat=True):
                    lock_run(run_id, request.user)
                    count += 1
        except (ValidationError, ValueError) as error:
            self.message_user(request, str(error), level=messages.ERROR)
            return
        self.message_user(
            request, f"Locked {count} experiment(s).", level=messages.SUCCESS
        )

    @admin.action(
        description="Explicitly unlock selected experiments (superuser and reason required)"
    )
    def unlock_experiments(self, request, queryset):
        try:
            with transaction.atomic():
                count = 0
                for run_id in queryset.order_by("pk").values_list("pk", flat=True):
                    unlock_run(
                        run_id, request.user, request.POST.get("unlock_reason", "")
                    )
                    count += 1
        except ValidationError as error:
            self.message_user(request, str(error), level=messages.ERROR)
            return
        self.message_user(
            request,
            f"Unlocked {count} experiment(s); reasons and prior hashes recorded.",
            level=messages.WARNING,
        )


@admin.register(SensorSample)
class SampleAdmin(EvidenceAdmin):
    form = ResearchAdminForm
    list_display = ("id", "run", "timestamp", "sequence_number", "quality_flag")
    list_filter = ("quality_flag", "source")
    raw_id_fields = ("run",)


@admin.register(FPGAImplementation)
class ImplementationAdmin(EvidenceAdmin):
    form = ResearchAdminForm


@admin.register(EventMarker)
class EventAdmin(EvidenceAdmin):
    form = ResearchAdminForm


@admin.register(ExperimentUnlockAudit)
class UnlockAuditAdmin(admin.ModelAdmin):
    list_display = ("run", "user", "unlocked_at", "reason")
    readonly_fields = tuple(field.name for field in ExperimentUnlockAudit._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
