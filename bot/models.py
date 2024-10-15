import uuid

from django.db import models
from django.db.models import Sum


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=5, decimal_places=2)

    # Optionally add image, description, etc.

    def __str__(self):
        return self.name


class Customer(models.Model):
    BARISTA = 'barista'
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        (BARISTA, 'Barista'),
    )

    user_id = models.IntegerField(unique=True)  # Telegram user ID
    username = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    qr_code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    coffees_count = models.IntegerField(default=0)
    coffees_free = models.IntegerField(default=0)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='customer')

    def __str__(self):
        return self.username or f"User {self.user_id}"

    def is_barista(self):
        return self.role == self.BARISTA


class Order(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
    )
    user_created = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='user_created')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    products = models.ManyToManyField(Product, through='OrderItem')
    created_at = models.DateTimeField(auto_now_add=True)
    is_anonymous = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    free_drinks = models.IntegerField(default=0)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"Order {self.id} - {'Anonymous' if self.is_anonymous else self.customer}"

    def total_coffees(self):
        return OrderItem.objects.filter(order=self,
                                        product__category__name='Coffee').aggregate(sum=Sum('quantity'))['sum']

    def total_price(self):
        total = 0
        used_free = 0
        for item in OrderItem.objects.filter(order=self).select_related('product'):
            if self.free_drinks == item.quantity:
                used_free += item.quantity
            elif self.free_drinks > item.quantity:
                used_free += item.quantity
            elif self.free_drinks < item.quantity:
                quantity = item.quantity - self.free_drinks
                total += quantity * item.product.price
                used_free += self.free_drinks
            else:
                total += item.quantity * item.product.price

        return total, used_free


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
