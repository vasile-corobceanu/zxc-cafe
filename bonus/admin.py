# bonus/admin.py

from django.contrib import admin

from .models import TgUser, Order, OrderItem, Category, Product


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('session_name', 'user_display', 'status', 'date')
    search_fields = ('session_name', 'user__username')
    list_filter = ('status', 'date')
    inlines = [OrderItemInline]

    def user_display(self, obj):
        return obj.user.username if obj.user else "Anonim"

    user_display.short_description = 'Utilizator'


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity')
    search_fields = ('order__session_name', 'product__name')


@admin.register(TgUser)
class TgUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'first_name', 'role', 'purchase_count')
    search_fields = ('username', 'first_name', 'user_id')
    list_filter = ('role',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price')
    list_filter = ('category',)
    search_fields = ('name',)
