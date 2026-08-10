from django.contrib import admin

from itr.models import AuditLogEntry, TaxReturn


@admin.register(TaxReturn)
class TaxReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'pan', 'ay', 'owner', 'version', 'updated_at')
    list_filter = ('ay',)
    search_fields = ('pan',)


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'tax_return', 'kind', 'actor', 'at')
    list_filter = ('kind',)
