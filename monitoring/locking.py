"""Transactional evidence guards shared by ORM, API, admin and package export.

Application writes acquire the experiment row before touching scientific evidence.
PostgreSQL consequently serializes ingestion with finalization. Direct SQL/database
administrator access is outside the application trust boundary.
"""

from contextlib import contextmanager

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

INTEGRITY_FIELDS = frozenset(
    ("dataset_sha256", "research_package_sha256", "integrity_generated_at")
)
LOCK_FIELDS = frozenset(("locked_at", "locked_by", "locked_by_id"))


@contextmanager
def protected_write(
    run_ids=(), implementation_ids=(), *, using="default", protect_shared=True
):
    """Lock shared configurations first, then experiments in stable ID order."""
    from .models import ExperimentRun, FPGAImplementation

    with transaction.atomic(using=using):
        implementations = sorted({v for v in implementation_ids if v is not None})
        if implementations:
            list(
                FPGAImplementation.objects.using(using)
                .filter(pk__in=implementations)
                .order_by("pk")
                .select_for_update()
            )
        ids = {v for v in run_ids if v is not None}
        if implementations and protect_shared:
            ids.update(
                ExperimentRun.objects.using(using)
                .filter(implementation_id__in=implementations)
                .values_list("pk", flat=True)
            )
        runs = list(
            ExperimentRun.objects.using(using)
            .filter(pk__in=ids)
            .order_by("pk")
            .select_for_update()
        )
        if any(run.status == "LOCKED" for run in runs):
            raise ValidationError(
                "Locked experiment evidence is immutable; explicitly unlock it first."
            )
        yield runs


@contextmanager
def protected_snapshot(run_id, *, using="default"):
    """Freeze run/configuration while canonical exports or lock actions execute."""
    from .models import ExperimentRun, FPGAImplementation

    with transaction.atomic(using=using):
        implementation_id = (
            ExperimentRun.objects.using(using)
            .values_list("implementation_id", flat=True)
            .get(pk=run_id)
        )
        if implementation_id is not None:
            FPGAImplementation.objects.using(using).select_for_update().get(
                pk=implementation_id
            )
        run = ExperimentRun.objects.using(using).select_for_update().get(pk=run_id)
        # A concurrent reassignment must never leave the new configuration unlocked.
        if (
            run.implementation_id != implementation_id
            and run.implementation_id is not None
        ):
            raise ValidationError(
                "FPGA configuration changed concurrently; retry finalization."
            )
        yield run


def _has_evidence(run):
    return run.samples.exists() or (
        hasattr(run, "hil_references") and run.hil_references.exists()
    )


def _check_run_values(values, originals=()):
    if "status" in values and not isinstance(values["status"], str):
        raise ValidationError(
            "Experiment lifecycle updates require an explicit status value."
        )
    if (
        values.get("status") == "LOCKED"
        or (INTEGRITY_FIELDS | LOCK_FIELDS) & values.keys()
    ):
        raise ValidationError(
            "Lock and integrity fields are managed by the research finalization actions."
        )
    if "source" in values:
        for original in originals:
            if values["source"] != original.source and _has_evidence(original):
                raise ValidationError(
                    {"source": "Cannot change source after evidence has been logged."}
                )


class LockProtectedQuerySet(models.QuerySet):
    @contextmanager
    def _guard(self, values=None, objects=()):
        values = values or {}
        relation = self.model.lock_relation
        run_ids, implementation_ids = set(), set()
        if relation == "self":
            targets = list(self.values_list("pk", "implementation_id"))
            run_ids.update(pk for pk, _ in targets)
            implementation_ids.update(parent for _, parent in targets)
            implementation_ids.update(
                getattr(obj, "implementation_id", None) for obj in objects
            )
            if "implementation" in values or "implementation_id" in values:
                implementation = values.get(
                    "implementation_id", values.get("implementation")
                )
                implementation_ids.add(getattr(implementation, "pk", implementation))
        elif relation == "implementation":
            targets = [(pk, pk) for pk in self.values_list("pk", flat=True)]
            implementation_ids.update(pk for pk, _ in targets)
            implementation_ids.update(obj.pk for obj in objects if obj.pk)
        else:
            targets = list(self.values_list("pk", relation + "_id"))
            run_ids.update(parent for _, parent in targets)
            run_ids.update(getattr(obj, relation + "_id", None) for obj in objects)
            if relation in values or relation + "_id" in values:
                run = values.get(relation + "_id", values.get(relation))
                if hasattr(run, "resolve_expression"):
                    raise ValidationError(
                        "Experiment reassignment requires an explicit run ID."
                    )
                run_ids.add(getattr(run, "pk", run))
        with protected_write(
            run_ids,
            implementation_ids,
            using=self.db,
            protect_shared=relation == "implementation",
        ) as runs:
            # Freeze the selected IDs so a concurrent insert cannot become an
            # unguarded update/delete target. Recheck child ownership after the
            # parent locks: reassignment before lock acquisition requires retry.
            selected = self.model.objects.using(self.db).filter(
                pk__in=[pk for pk, _ in targets]
            )
            if targets and relation not in ("self", "implementation"):
                current_parents = set(selected.values_list(relation + "_id", flat=True))
                if not current_parents <= run_ids:
                    raise ValidationError(
                        "Evidence ownership changed concurrently; retry the explicit update."
                    )
            if relation == "self":
                _check_run_values(values, runs)
            yield selected

    def update(self, **kwargs):
        with self._guard(kwargs) as selected:
            # Capture original parents as well as new parents for reassignment.
            self._invalidate()
            result = models.QuerySet.update(selected, **kwargs)
            selected._invalidate()
            return result

    def delete(self):
        with self._guard() as selected:
            return models.QuerySet.delete(selected)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        if not objs:
            return objs
        # Conflict updates can overwrite a row whose parent differs from input.
        if kwargs.get("update_conflicts"):
            raise ValidationError(
                "Conflict updates are unavailable for scientific evidence; update explicit rows."
            )
        with self.none()._guard(objects=objs):
            if self.model.lock_relation == "self":
                for obj in objs:
                    obj._check_run_save(None)
            result = super().bulk_create(objs, **kwargs)
            self._invalidate(objects=objs)
            return result

    def bulk_update(self, objs, fields, **kwargs):
        objs = list(objs)
        if self.model.lock_relation == "self" and (
            set(fields)
            & (
                INTEGRITY_FIELDS
                | LOCK_FIELDS
                | {"status", "source", "implementation", "implementation_id"}
            )
        ):
            raise ValidationError(
                "Update experiment lifecycle and provenance through explicit row saves."
            )
        if self.model.lock_relation not in ("self", "implementation") and set(
            fields
        ) & {"run", "run_id"}:
            raise ValidationError(
                "Experiment reassignment requires explicit row saves."
            )
        with self.filter(pk__in=[obj.pk for obj in objs])._guard(objects=objs):
            return super().bulk_update(objs, fields, **kwargs)

    def _invalidate(self, objects=()):
        from .models import ExperimentRun, invalidate_run_summary

        relation = self.model.lock_relation
        if relation == "self":
            ids = (
                self.values_list("pk", flat=True)
                if not objects
                else [obj.pk for obj in objects]
            )
        elif relation == "implementation":
            ids = ExperimentRun.objects.filter(
                implementation_id__in=self.values("pk")
            ).values_list("pk", flat=True)
        else:
            ids = (
                self.values_list(relation + "_id", flat=True)
                if not objects
                else [getattr(obj, relation + "_id") for obj in objects]
            )
        for run_id in set(ids):
            invalidate_run_summary(run_id)


class LockProtectedModel(models.Model):
    lock_relation = "run"
    objects = LockProtectedQuerySet.as_manager()

    class Meta:
        abstract = True

    def _check_run_save(self, original):
        if self.lock_relation != "self":
            return
        if self.status == "LOCKED":
            raise ValidationError("Use the protected Lock Experiment action.")
        for name in INTEGRITY_FIELDS | {"locked_at", "locked_by_id"}:
            if getattr(self, name) != (
                getattr(original, name)
                if original
                else self._meta.get_field(name.removesuffix("_id")).get_default()
            ):
                raise ValidationError(
                    "Lock and integrity fields are managed by research finalization actions."
                )
        if original and self.source != original.source and _has_evidence(original):
            raise ValidationError(
                {"source": "Cannot change source after evidence has been logged."}
            )

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        queryset = (
            type(self).objects.using(using).filter(pk=self.pk)
            if self.pk
            else type(self).objects.using(using).none()
        )
        with queryset._guard(objects=[self]):
            original = queryset.first() if self.pk else None
            self._check_run_save(original)
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with type(self).objects.using(using).filter(pk=self.pk)._guard(objects=[self]):
            return super().delete(*args, **kwargs)


def update_integrity(
    run, *, dataset_sha256, research_package_sha256, integrity_generated_at=None
):
    """Narrow internal persistence path; never exposes arbitrary field updates."""
    from .models import ExperimentRun, invalidate_run_summary

    for value in (dataset_sha256, research_package_sha256):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValidationError(
                "Integrity digests must be lowercase SHA256 hex strings."
            )
    values = dict(
        dataset_sha256=dataset_sha256,
        research_package_sha256=research_package_sha256,
        integrity_generated_at=integrity_generated_at or timezone.now(),
    )
    models.QuerySet.update(ExperimentRun.objects.filter(pk=run.pk), **values)
    for key, value in values.items():
        setattr(run, key, value)
    invalidate_run_summary(run.pk)


def lock_run(run_id, user=None):
    from .models import ExperimentRun, invalidate_run_summary
    from .research_package import generate_package

    with protected_snapshot(run_id) as run:
        if run.status != "COMPLETED":
            raise ValidationError("Only a COMPLETED experiment can be locked.")
        values = dict(
            status="LOCKED",
            locked_at=timezone.now(),
            locked_by_id=user.pk if user and user.is_authenticated else None,
        )
        models.QuerySet.update(ExperimentRun.objects.filter(pk=run.pk), **values)
        for key, value in values.items():
            setattr(run, key, value)
        generate_package(run, persist=True, _initial_lock=True)
        invalidate_run_summary(run.pk)
        return run


def unlock_run(run_id, user, reason):
    from .models import ExperimentRun, ExperimentUnlockAudit, invalidate_run_summary

    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or not user.is_superuser
    ):
        raise PermissionDenied(
            "Only an authenticated superuser may unlock experimental evidence."
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError(
            {"reason": "An explicit reason is required for the immutable unlock audit."}
        )
    with protected_snapshot(run_id) as run:
        if run.status != "LOCKED":
            raise ValidationError("Only a LOCKED experiment can be unlocked.")
        ExperimentUnlockAudit.objects.create(
            run=run,
            user=user,
            reason=reason.strip(),
            locked_at=run.locked_at,
            dataset_sha256=run.dataset_sha256,
            research_package_sha256=run.research_package_sha256,
        )
        values = dict(
            status="COMPLETED",
            locked_at=None,
            locked_by_id=None,
            dataset_sha256="",
            research_package_sha256="",
            integrity_generated_at=None,
        )
        models.QuerySet.update(ExperimentRun.objects.filter(pk=run.pk), **values)
        for key, value in values.items():
            setattr(run, key, value)
        invalidate_run_summary(run.pk)
        return run
