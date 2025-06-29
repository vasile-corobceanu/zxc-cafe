import logging
import re

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from telethon import TelegramClient, events, Button

from bot.models import Customer, Category, Order, Product, OrderItem
from bot.utils import generate_qr_code

current_order = {}
last_message_id = {}
current_customer = {}
awaiting_quantity = {}


class Command(BaseCommand):
    help = 'Pornește botul Telegram'
    coffee_limit = 5

    def handle(self, *args, **options):
        API_ID = getattr(settings, 'TELEGRAM_API_ID', 'YOUR_API_ID')
        API_HASH = getattr(settings, 'TELEGRAM_API_HASH', 'YOUR_API_HASH')
        BOT_TOKEN = getattr(settings, 'TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')

        client = TelegramClient('coffee_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

        @client.on(events.NewMessage(pattern='/start'))
        async def start(event):
            user = await event.get_sender()
            me = await client.get_me()
            user_id = user.id
            username = user.username
            bot_username = me.username

            if event.raw_text.startswith('/start user_id'):
                customer_id = event.raw_text.lstrip('/start user_id')
                customer = await sync_to_async(Customer.objects.get)(user_id=customer_id)
                current_customer[user_id] = customer
                buttons = [
                    Button.inline('Adaugă produse', data="go_to_menu"),
                ]
                message = "QR Code scanat!"
                if customer.coffees_free:
                    message += f"\nClientul are {customer.coffees_free} gratis!"
                    buttons.append(Button.inline('Folosește', data="use_free"))

                if current_order.get(user_id):
                    buttons.append(Button.inline('Finalizați comanda', data="finish"))

                await event.respond(message, buttons=buttons)
                return

            customer, created = await sync_to_async(Customer.objects.get_or_create)(
                user_id=user.id,
                defaults={
                    'username': user.username,
                    'first_name': user.first_name,
                    'role': 'barista' if user.username in settings.BARISTA_USERNAMES else 'customer',
                }
            )
            if created:
                qr_image = generate_qr_code(bot_username, user_id)
                await client.send_file(event.chat_id, qr_image, caption=f"Cod QR pentru @{username}")
            else:
                if customer.is_barista():
                    await menu(event)
                    return

                await event.respond("Bine ați revenit la Coffee Shop-ul nostru!")

        @client.on(events.NewMessage(pattern='/qr'))
        async def qr(event):
            user = await event.get_sender()
            me = await client.get_me()
            user_id = user.id
            bot_username = me.username

            qr_image = generate_qr_code(bot_username, user_id)
            caption = "Aici este codul dumneavoastră QR unic. Prezentați-l baristei când comandați."
            await client.send_file(event.chat_id, qr_image, caption=caption)

        @client.on(events.NewMessage(pattern='/menu'))
        async def menu(event):
            user = await event.get_sender()
            customer = await self.get_or_create_user(user)
            if not customer.is_barista():
                return

            categories = await sync_to_async(list)(Category.objects.prefetch_related('products').all())
            buttons = [
                [Button.inline(cat.name, data=f"category_{cat.id}")] for cat in categories
            ]

            await event.respond("Selectați categoria:", buttons=buttons)

        @client.on(events.NewMessage(pattern='/now'))
        async def now(event):
            user = await event.get_sender()
            customer = await self.get_or_create_user(user)
            if not customer.is_barista():
                return

            order = current_order.get(user.id)
            if not order:
                await event.respond('Nu sunt produse adăugate!')
                return

            order_items = await sync_to_async(list)(order.items.select_related('product').all())
            total_price, used_free = await sync_to_async(order.total_price)()
            order_summary = '\n'.join([
                f"{item.product.name} x {item.quantity}" for item in order_items
            ])
            buttons = [
                Button.inline('Adaugă încă', data="go_to_menu"),
                Button.inline('Finalizați comanda', data='check_finish')
            ]
            await event.respond(f"Comanda curentă:\n{order_summary}\n"
                                f"Preț Total: {total_price}\n"
                                f"Gratis: {used_free} cafele\n\n",
                                buttons=buttons)

        @client.on(events.CallbackQuery(data=re.compile('category_(\\d+)')))
        async def category_selected(event):
            category_id = int(event.data_match.group(1))
            category = await sync_to_async(Category.objects.get)(id=category_id)
            products = await sync_to_async(list)(category.products.all())

            if not products:
                await event.edit("Nu există produse în această categorie.")
                return

            buttons = [
                [Button.inline(f"{item.name} - {item.price} MDL", data=f"product_{item.id}")] for item in products
            ]

            await event.edit("Alege un produs:", buttons=buttons)

        @client.on(events.CallbackQuery(data=re.compile('product_(\\d+)')))
        async def product_selected(event):
            product_id = int(event.data_match.group(1))
            product = await sync_to_async(Product.objects.get)(id=product_id)

            if not product:
                await event.edit("Nu există așa produs.")
                return
            quantity_options = ['1', '2', '3', '4', '5']
            buttons = [
                [Button.inline(item, data=f'quantity_{product_id}_{item}') for item in quantity_options],
                [Button.inline('Mai multe', data=f'quantity_{product_id}_more')]
            ]

            await event.edit("Alege cantitatea produselor:", buttons=buttons)

        @client.on(events.CallbackQuery(data=re.compile('quantity_(\\d+)_more')))
        async def quantity_more(event):
            user_id = event.sender_id
            product_id = int(event.data_match.group(1))
            awaiting_quantity[user_id] = product_id
            await event.respond('Introduceți cantitatea dorită (număr întreg):')

        @client.on(events.CallbackQuery(data=re.compile('quantity_(\\d+)_(\\d+)')))
        async def quantity_selected(event):
            user = await event.get_sender()
            product_id = int(event.data_match.group(1))
            quantity = int(event.data_match.group(2))
            product = await sync_to_async(Product.objects.get)(id=product_id)
            if not product:
                await event.edit("Eroare: produsul selectat nu a fost găsit.")

            order = current_order.get(user.id)

            if not order:
                barista = await sync_to_async(Customer.objects.get)(user_id=user.id)
                order = await sync_to_async(Order.objects.create)(
                    status='pending',
                    user_created=barista,
                )
                current_order[user.id] = order

            existing_item = await sync_to_async(OrderItem.objects.filter(order=order, product=product).first)()
            if existing_item:
                existing_item.quantity += quantity
                await sync_to_async(existing_item.save)()
            else:
                await sync_to_async(OrderItem.objects.create)(
                    order=order,
                    product=product,
                    quantity=quantity
                )

            order_items = await sync_to_async(list)(order.items.select_related('product').all())
            total_price, used_free = await sync_to_async(order.total_price)()
            order_summary = '\n'.join([
                f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
                for item in order_items
            ])
            buttons = [
                Button.inline('Adaugă încă', data="go_to_menu"),
                Button.inline('Finalizați comanda', data='check_finish')
            ]

            message = await event.edit(f"Ați adăugat {quantity} x {product.name} la comanda curentă.\n\n"
                                       f"Comanda curentă:\n{order_summary}\n"
                                       f"Preț Total: {total_price}\n"
                                       f"Gratis: {used_free} cafele\n\n",
                                       buttons=buttons)
            last_message_id[user.id] = message.id

        @client.on(events.NewMessage)
        async def handle_new_message(event):
            user_id = event.sender_id
            if user_id in awaiting_quantity:
                text = event.raw_text.strip()
                if text.isdigit():
                    quantity = int(text)
                    product_id = awaiting_quantity.pop(user_id)
                    product = await sync_to_async(Product.objects.get)(id=product_id)

                    if not product:
                        await event.respond("Eroare: produsul selectat nu a fost găsit.")
                        return

                    order = current_order.get(user_id)
                    if not order:
                        order = await sync_to_async(Order.objects.create)(
                            status='pending'
                        )
                        current_order[user_id] = order

                    existing_item = await sync_to_async(OrderItem.objects.filter(order=order, product=product).first)()

                    if existing_item:
                        existing_item.quantity += quantity
                        await sync_to_async(existing_item.save)()
                    else:
                        await sync_to_async(OrderItem.objects.create)(
                            order=order,
                            product=product,
                            quantity=quantity
                        )
                    order_items = await sync_to_async(list)(order.items.select_related('product').all())
                    total_price, used_free = await sync_to_async(order.total_price)()
                    order_summary = '\n'.join([
                        f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
                        for item in order_items
                    ])
                    buttons = [
                        Button.inline('Adaugă încă', data="go_to_menu"),
                        Button.inline('Finalizați comanda', data='check_finish')
                    ]
                    message = await event.respond(f"Ați adăugat {quantity} x {product.name} la comanda curentă.\n\n"
                                                  f"Comanda curentă:\n{order_summary}\n"
                                                  f"Preț Total: {total_price}\n"
                                                  f"Gratis: {used_free} cafele\n\n",
                                                  buttons=buttons)
                    last_message_id[user_id] = message.id
                else:
                    await event.respond('Vă rugăm să introduceți un număr întreg.')

        @client.on(events.CallbackQuery(data='go_to_menu'))
        async def go_to_menu(event):
            user_id = event.sender_id
            message = await event.get_message()
            await message.delete()
            if user_id in last_message_id:
                await client.delete_messages(event.chat_id, [last_message_id[user_id]])

            await menu(event)

        @client.on(events.CallbackQuery(pattern='finish'))
        async def finish(event):
            user = await event.get_sender()
            c_order = current_order.get(user.id)

            if not c_order:
                await event.edit("Nu există comenzi active.")
                await menu(event)
                return

            customer = current_customer.get(user.id)

            if customer:
                purchased_coffees = await sync_to_async(c_order.total_coffees)()
                coffee_free = abs(purchased_coffees - c_order.free_drinks) or 1 if c_order.free_drinks else 0
                c_order.free_drinks = coffee_free

                if purchased_coffees and not coffee_free:
                    number_of_free_coffees = (purchased_coffees + customer.coffees_count) // self.coffee_limit

                    if number_of_free_coffees:
                        customer.coffees_count += purchased_coffees
                        customer.coffees_count = customer.coffees_count - self.coffee_limit * number_of_free_coffees
                        customer.coffees_free += number_of_free_coffees
                        message = f"🎉 Felicitări! Ați câștigat {number_of_free_coffees} cafea/cafele gratuită(e)! 🎉"
                        logging.info(message)
                        await client.send_message(customer.user_id, message)
                    else:
                        customer.coffees_count += purchased_coffees
                else:
                    customer.coffees_free -= coffee_free

                await sync_to_async(customer.save)()
                c_order.customer = customer

            c_order.status = 'confirmed'
            c_order.is_anonymous = not customer
            total_price, used_free = await sync_to_async(c_order.total_price)()
            c_order.total_paid = total_price
            await sync_to_async(c_order.save)()
            current_order.pop(user.id, None)
            current_customer.pop(user.id, None)
            order_items = await sync_to_async(list)(c_order.items.select_related('product').all())
            order_summary = '\n'.join([
                f"- {item.product.name} x {item.quantity}" for item in order_items
            ])
            await event.edit(f"Comanda a fost adăugată cu succes!\n{order_summary}\nPreț Total: {total_price}")

        @client.on(events.CallbackQuery(pattern='check_finish'))
        async def check_finish(event):
            user = await event.get_sender()
            c_order = current_order.get(user.id)
            if c_order:
                coffee_count = await sync_to_async(c_order.total_coffees)()
            else:
                coffee_count = 0

            if current_customer.get(user.id) or not coffee_count:
                await finish(event)
                return
            buttons = [
                Button.inline('Nu are QR', data="finish"),
                Button.inline('Scanează QR', data='scan_qr_info')
            ]
            await event.edit(f"Selectați pentru a finaliza comanda!", buttons=buttons)

        @client.on(events.CallbackQuery(pattern='scan_qr_info'))
        async def scan_qr_info(event):
            await event.edit(f"Deschide camera și scanează Codul QR!")

        @client.on(events.CallbackQuery(pattern='use_free'))
        async def use_free(event):
            user = await event.get_sender()
            customer = current_customer[user.id]
            print('customer use free', customer)
            if customer.coffees_free:
                c_order = current_order.get(user.id)
                if c_order:
                    c_order.customer = customer
                    c_order.free_drinks = customer.coffees_free
                    await sync_to_async(c_order.save)()
                else:
                    c_order = await sync_to_async(Order.objects.create)(
                        status='pending'
                    )
                    c_order.free_drinks = customer.coffees_free
                    await sync_to_async(c_order.save)()
                    current_order[user.id] = c_order

            order_items = await sync_to_async(list)(c_order.items.select_related('product').all())
            total_price, used_free = await sync_to_async(c_order.total_price)()
            order_summary = '\n'.join([
                f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
                for item in order_items
            ])
            buttons = [
                Button.inline('Adaugă încă', data="go_to_menu"),
                Button.inline('Finalizați comanda', data='check_finish')
            ]

            message = await event.edit(f"Comanda curentă:\n{order_summary}\n"
                                       f"Preț Total: {total_price}\n"
                                       f"Gratis: {used_free} cafele\n\n",
                                       buttons=buttons)
            last_message_id[user.id] = message.id

        @client.on(events.NewMessage(pattern='/order'))
        async def add_order(event):
            user = await event.get_sender()
            user_id = user.id
            try:
                customer = Customer.objects.get(user_id=user_id)
            except Customer.DoesNotExist:
                customer = None

            if customer:
                await event.respond("Cod QR funcționează")
                await finish(event)
            else:
                await event.respond("Problemă cu codul QR. Eroarea a fost salvată!")

        @client.on(events.NewMessage(pattern='/info'))
        async def info(event):
            user = await event.get_sender()
            try:
                customer = await sync_to_async(Customer.objects.get)(user_id=user.id)
            except Customer.DoesNotExist:
                customer = None

            if customer:
                if customer.is_barista():
                    today = timezone.now().date()

                    orders = await sync_to_async(list)(Order.objects.order_by('id').filter(created_at__date=today))

                    if not orders:
                        await event.respond("Nu există comenzi pentru astăzi.")
                        return

                    # Build the message
                    message = "Comenzile de astăzi:\n"
                    total = 0
                    count = 0
                    for order in orders:
                        order_items = await sync_to_async(list)(order.items.select_related('product').all())
                        order_summary = ', '.join([
                            f"{item.product.name} x {item.quantity}" for item in order_items
                        ])
                        total_price, used_free = await sync_to_async(order.total_price)()
                        total += total_price
                        count += 1
                        message += f"#{count}: {order_summary} = {total_price}\n"

                    message += f"\nTotal azi: {total} MDL\n\n"
                    await event.respond(message)
                    return

                purchases_left = (
                    self.coffee_limit - (customer.coffees_count % self.coffee_limit)
                    if customer.coffees_count % self.coffee_limit != 0 else 0
                )
                purchases_left += customer.coffees_free

                loyalty_status = (
                    "🎉 Aveți o cafea gratuită care vă așteaptă!"
                    if purchases_left == 0 else
                    f"Mai aveți nevoie de {purchases_left} achiziție(i) pentru a primi o cafea gratuită."
                )
                await event.respond(loyalty_status)

        print("Botul rulează...")
        client.run_until_disconnected()

    async def get_or_create_user(self, user):
        customer, created = await sync_to_async(Customer.objects.get_or_create)(
            user_id=user.id,
            defaults={
                'username': user.username,
                'first_name': user.first_name,
                'role': 'barista' if user.username in settings.BARISTA_USERNAMES else 'customer',
            }
        )
        return customer