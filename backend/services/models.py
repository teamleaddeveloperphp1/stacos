import uuid

from django.conf import settings
from django.db import models


class ServiceInterest(models.Model):
    """§9.1 "Notify me when it's ready" -- no email sending in this pass,
    just records interest."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='service_interests')
    slug = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'slug')]

    def __str__(self):
        return f'{self.user_id} interested in {self.slug}'
