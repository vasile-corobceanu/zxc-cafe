from datetime import timedelta

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.contrib.auth.models import User, Group
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Q, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from pytz import timezone as pytz_timezone
from unfold.admin import ModelAdmin, TabularInline

from .filters import BaristaUserFilter
from .models import Category, Product, Customer, Order, OrderItem, ProductSalesReport

admin.site.unregister(User)
admin.site.unregister(Group)


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity',)


class ProductInline(TabularInline):
    model = Product
    extra = 0


class OrderInline(TabularInline):
    model = Order
    fk_name = 'customer'
    fields = (
        'id', 'products_list', 'user_created', 'created_at_chisinau',
        'status', 'order_total', 'total_paid',
    )
    readonly_fields = (
        'id', 'products_list', 'user_created', 'created_at_chisinau',
        'status', 'order_total', 'total_paid',
    )
    can_delete = False
    extra = 0
    ordering = ('-id',)
    verbose_name_plural = 'Orders History'

    def has_add_permission(self, request, obj):
        return False  # Prevent adding orders from the Customer admin

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Optimize query by prefetching related items and products
        return qs.prefetch_related('items__product')

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
        return obj.user_created.first_name if obj.user_created else 'Anonymous'

    user_created.admin_order_field = 'user_created'
    user_created.short_description = 'User Created'


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
        return obj.user_created.first_name if obj.user_created else 'Anonymous'

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
    inlines = [ProductInline]


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ['name', 'category', 'price']
    list_filter = ['category']
    search_fields = ['name']


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ['first_name', 'username', 'coffees_count', 'coffees_free', 'total_paid', 'total_quantity']
    search_fields = ['username', 'user_id']
    list_filter = ['role']
    inlines = [OrderInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        qs = qs.annotate(
            total_paid_sum=Coalesce(
                Sum('order__total_paid', filter=Q(order__customer=F('id'))),
                0,
                output_field=DecimalField()
            ),
            total_quantity_sum=Coalesce(
                Sum('order__items__quantity', filter=Q(order__customer=F('id'))),
                0,
                output_field=IntegerField()
            ), )

        return qs

    def total_paid(self, obj):
        return obj.total_paid_sum

    total_paid.short_description = 'Total Paid'
    total_paid.admin_order_field = 'total_paid_sum'

    def total_quantity(self, obj):
        return obj.total_quantity_sum

    total_quantity.short_description = 'Total Quantity'
    total_quantity.admin_order_field = 'total_quantity_sum'


class DateRangeFilter(SimpleListFilter):
    title = 'Date Range'
    parameter_name = 'date_range'

    def lookups(self, request, model_admin):
        return [
            ('today', 'Today'),
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
        ]

    def queryset(self, request, queryset):
        # We'll handle filtering in the ModelAdmin's get_queryset
        return queryset


@admin.register(ProductSalesReport)
class ProductSalesReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'total_quantity_sold', 'total_sales')
    list_filter = ('category', DateRangeFilter,)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data['cl'].queryset
            total_sales_sum = qs.aggregate(total=Sum('total_sales'))['total'] or 0
            response.context_data['total_sales_sum'] = total_sales_sum
        except (AttributeError, KeyError):
            pass
        return response

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        date_range = request.GET.get('date_range')

        if date_range == 'today':
            today = timezone.now().date()
            start_date = end_date = today
        elif date_range == 'this_week':
            today = timezone.now().date()
            start_date = today - timedelta(days=today.weekday())
            end_date = today
        elif date_range == 'this_month':
            today = timezone.now().date()
            start_date = today.replace(day=1)
            end_date = today
        else:
            today = timezone.now().date()
            start_date = end_date = today

        qs = qs.annotate(
            total_quantity_sold=Sum(
                'orderitem__quantity',
                filter=Q(orderitem__order__created_at__date__gte=start_date) & Q(
                    orderitem__order__created_at__date__lte=end_date)
            ),
            total_sales=Sum(
                ExpressionWrapper(F('orderitem__quantity') * F('price'), output_field=DecimalField()),
                filter=Q(orderitem__order__created_at__date__gte=start_date) & Q(
                    orderitem__order__created_at__date__lte=end_date)
            )
        )

        qs = qs.filter(total_quantity_sold__gt=0)
        qs = qs.order_by('-total_sales')

        return qs

    def total_quantity_sold(self, obj):
        return obj.total_quantity_sold or 0

    total_quantity_sold.short_description = 'Total Quantity Sold'

    def total_sales(self, obj):
        return obj.total_sales or 0

    total_sales.short_description = 'Total Sales'
