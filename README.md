# ZXC Cafe

A Django-based coffee shop management system with Telegram bot integration.

## Features

- Customer management with role-based access
- Order management system
- Product catalog with categories
- Telegram bot interface
- Admin dashboard
- Bonus/loyalty system

## Setup

1. Install dependencies:
```bash
poetry install
```

2. Run database migrations:
```bash
python manage.py migrate
```

3. Load initial data:
```bash
python manage.py loaddata fixtures/categories.json
python manage.py loaddata fixtures/products.json
```

4. Create superuser:
```bash
python manage.py createsuperuser
```

## Running the Application

### Start Django server:
```bash
python manage.py runserver
```

### Start Telegram bot:
```bash
python manage.py run_telegram_bot
```

## Project Structure

- `bot/` - Telegram bot functionality and models
- `bonus/` - Loyalty/bonus system
- `fixtures/` - Initial data files
- `templates/` - HTML templates
- `static/` - Static files
- `zxc/` - Django project settings