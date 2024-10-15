from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from bot.models import Customer


class BaristaUserFilter(admin.SimpleListFilter):
    title = _('User Created')
    parameter_name = 'user_created'

    def lookups(self, request, model_admin):
        try:
            return [(user.id, user.username) for user in Customer.objects.filter(role=Customer.BARISTA)]
        except Customer.DoesNotExist:
            return []

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(user_created__id=self.value())
        return queryset
