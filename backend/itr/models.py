import uuid

from django.conf import settings
from django.db import models

from itr.model_blank import blank_return_model


def _default_return_data():
    # tenantId/returnId are filled in by TaxReturn.save() on first insert,
    # once the primary key exists; this default only supplies the shape.
    return blank_return_model(tenant_id='', return_id='')


class TaxReturn(models.Model):
    """One ITR-1 draft. Holds the full canonical ReturnModel as a single
    JSONField per architecture mandate 3 ("one canonical in-memory model") --
    not normalized across dozens of tables for every nested schedule."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tax_returns')
    pan = models.CharField(max_length=10, blank=True)
    ay = models.CharField(max_length=7, default='2026-27')
    model_version = models.IntegerField(default=1)
    data = models.JSONField(default=_default_return_data)
    screen_status = models.JSONField(default=dict, blank=True)

    # Optimistic locking: incremented on every save so a concurrent edit can
    # be detected (compare the version you loaded against the current one
    # before writing).
    version = models.IntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['owner', 'ay']),
            models.Index(fields=['pan']),
        ]

    def __str__(self):
        return f'ITR-1 {self.ay} · {self.pan or "(no PAN)"} · #{self.pk}'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.data.get('returnId'):
            self.data['tenantId'] = str(self.owner_id)
            self.data['returnId'] = str(self.pk)
            super().save(update_fields=['data'])

    def bump_version(self):
        """Call once per edit, after the submitted `version` has been checked
        against the current one (see itr.views._check_version_conflict),
        so a concurrent editor's next save is detected as stale. This is a
        Python-level check-then-increment, not an atomic DB-level compare-
        and-swap -- adequate for this module's demo-scale single-process
        deployment, not a guarantee under real concurrent writers."""
        self.version += 1


class AuditLogEntry(models.Model):
    """Every field change, validation run, and JSON generation, per
    architecture mandate 6 ("full audit trail")."""

    KIND_FIELD_CHANGE = 'field_change'
    KIND_VALIDATION_RUN = 'validation_run'
    KIND_JSON_GENERATION = 'json_generation'
    KIND_ADVISORY_ACK = 'advisory_ack'
    KIND_CHOICES = [
        (KIND_FIELD_CHANGE, 'Field change'),
        (KIND_VALIDATION_RUN, 'Validation run'),
        (KIND_JSON_GENERATION, 'JSON generation'),
        (KIND_ADVISORY_ACK, 'Advisory acknowledgement'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tax_return = models.ForeignKey(TaxReturn, on_delete=models.CASCADE, related_name='audit_log')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)

    field_path = models.CharField(max_length=255, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    # Free-form payload: a validation report snapshot, a generation hash, etc.
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=['tax_return', 'at'])]
        ordering = ['-at']

    def __str__(self):
        return f'{self.get_kind_display()} on return #{self.tax_return_id} at {self.at}'
