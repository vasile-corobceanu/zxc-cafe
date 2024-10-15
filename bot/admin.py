from django.contrib import admin
from django.utils import timezone
from pytz import timezone as pytz_timezone

from .filters import BaristaUserFilter
from .models import Category, Product, Customer, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_filter = ('created_at', BaristaUserFilter, 'free_drinks', 'products__category')
    list_display = (
        'id',
        'products_list',
        'user_created',
        'created_at_chisinau',
        'customer',
        'status',
        'order_total',
        'total_paid',
    )
    inlines = [OrderItemInline]
    search_fields = ['id', 'customer__username', 'customer__user_id']
    list_display_links = ('products_list',)

    def created_at_chisinau(self, obj):
        chisinau_tz = pytz_timezone('Europe/Chisinau')
        return timezone.localtime(obj.created_at, chisinau_tz).strftime('%Y-%m-%d %H:%M:%S')

    created_at_chisinau.admin_order_field = 'created_at'
    created_at_chisinau.short_description = 'Created At (Chisinau)'

    def products_list(self, obj):
        products = obj.items.select_related('product')
        product_names = [item.product.name for item in products]
        return ', '.join(product_names)

    products_list.short_description = 'Products'

    def order_total(self, obj):
        total, _ = obj.total_price()
        return '{:.2f}'.format(total)

    order_total.short_description = 'Total Price'

    def user_created(self, obj):
        return obj.user_created.username if obj.user_created else 'Anonymous'

    user_created.admin_order_field = 'user_created'
    user_created.short_description = 'User Created'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price']
    list_filter = ['category']
    search_fields = ['name']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['username', 'user_id', 'coffees_count']
    search_fields = ['username', 'user_id']
