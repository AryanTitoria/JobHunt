from django.contrib import admin
from .models import Job, Source, Sighting, Task, AIEvent, ProviderHealth

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'provider', 'active', 'is_demo', 'last_seen')
    search_fields = ('title', 'company')
    list_filter = ('active', 'provider', 'is_demo')

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('key', 'kind', 'last_success', 'count', 'error')

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('kind', 'status', 'created', 'finished')
    readonly_fields = ('payload',)

admin.site.register(ProviderHealth)
admin.site.site_header = 'JobSearch administration'
