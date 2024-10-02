from django.db import models


class TgUser(models.Model):
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('barista', 'Barista'),
    )
    user_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    purchase_count = models.IntegerField(default=0)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='customer')

    def __str__(self):
        return f"{self.username} ({self.role})" or str(self.user_id)


class Order(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
    )
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, null=True, blank=True)
    item = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    date = models.DateTimeField(auto_now_add=True)
    session_name = models.CharField(max_length=255, unique=True, null=True, blank=True)

    def __str__(self):
        user_str = self.user.username if self.user else "Anonim"
        return f"Order {self.id}: {self.item} by {user_str} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class Category(models.Model):
    name = models.CharField("Nume Categorie", max_length=255)

    class Meta:
        verbose_name = 'Categorie'
        verbose_name_plural = 'Categorii'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name="Categorie"
    )
    name = models.CharField("Nume Produs", max_length=255)
    price = models.DecimalField("Preț", max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = 'Produs'
        verbose_name_plural = 'Produse'

    def __str__(self):
        return f"{self.name} ({self.category.name})"
