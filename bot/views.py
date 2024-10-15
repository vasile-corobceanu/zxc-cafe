from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import Order


def dashboard_callback(request, context):
    # Get current date and calculate the date one week ago
    today = timezone.now().date()
    one_week_ago = today - timedelta(days=7)

    # Query to count orders grouped by date for the last 7 days
    orders = Order.objects.filter(created_at__gte=one_week_ago).extra(
        select={'day': "DATE(created_at)"}
    ).values('day').annotate(order_count=Count('id')).order_by('day')

    # Prepare data for the line chart
    chart_labels = [order['day'].strftime('%Y-%m-%d') for order in orders]
    chart_values = [order['order_count'] for order in orders]

    # Update the context with line chart data
    context.update({
        "line_chart_data": {
            'labels': chart_labels,
            'datasets': [{
                'label': 'Number of Orders',
                'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                'borderColor': 'rgba(75, 192, 192, 1)',
                'borderWidth': 1,
                'data': chart_values,
            }],
        }
    })

    return context
