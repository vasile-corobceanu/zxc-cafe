from django.contrib import admin
from django.contrib.auth.models import User, Group
from django.db.models import ExpressionWrapper, F, DecimalField
from django.utils import timezone
from pytz import timezone as pytz_timezone
from unfold.admin import ModelAdmin, TabularInline

from .filters import BaristaUserFilter
from .models import Category, Product, Customer, Order, OrderItem

admin.site.unregister(User)
admin.site.unregister(Group)


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 1


@admin.register(Order)
class OrderAdmin(ModelAdmin):
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
        product_names = [f'{item.quantity}-{item.product.name}' for item in products]
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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            order_total_calc=ExpressionWrapper(
                F('total_paid'),
                output_field=DecimalField()
            )
        )
        return qs

    list_totals = {
        'order_total': {
            'field': 'order_total_calc',
            'position': 'footer',
        },
        'total_paid': {
            'field': 'total_paid',
            'position': 'footer',
        },
    }

    def order_total(self, obj):
        return obj.order_total_calc

    order_total.short_description = 'Order Total'

    def total_paid(self, obj):
        return obj.total_paid or 0

    total_paid.short_description = 'Total Paid'
    total_paid.admin_order_field = 'total_paid'


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ['name', 'category', 'price']
    list_filter = ['category']
    search_fields = ['name']


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ['username', 'user_id', 'coffees_count']
    search_fields = ['username', 'user_id']
