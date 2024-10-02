import asyncio
import logging
import uuid
from datetime import datetime
from io import BytesIO

import qrcode
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from qrcode.image.pil import PilImage
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    Update, InputFile, ReplyKeyboardMarkup,
)
from telegram.ext import (
    CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters, Application,
)

from bonus.models import TgUser, Order, Category, Product, OrderItem


class Command(BaseCommand):
    help = 'Rulează botul Telegram.'
    logger = logging.getLogger(__name__)

    GET_ITEM = 1
    GET_QUANTITY = 2
    GET_MANUAL_QUANTITY = 3
    FINALIZE_ORDER = 4

    PURCHASES_FOR_FREE_COFFEE = 5

    keyboard_customer = [
        [
            InlineKeyboardButton("Start", callback_data='start'),
            InlineKeyboardButton("Obține codul QR", callback_data='qr'),
        ],
        [
            InlineKeyboardButton("Informații", callback_data='info'),
        ],
    ]
    keyboard_barista = [
        [
            InlineKeyboardButton("Meniu Barista", callback_data='barista_menu'),
        ],
    ]

    def get_keyboard(self, user_role):
        if user_role == 'barista':
            return InlineKeyboardMarkup(self.keyboard_customer + self.keyboard_barista)
        else:
            return InlineKeyboardMarkup(self.keyboard_customer)

    def handle(self, *args, **options):
        application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

        # Add handlers using chaining
        application.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                self.GET_ITEM: [MessageHandler(filters.TEXT, self.receive_item)],
                self.GET_QUANTITY: [
                    MessageHandler(filters.Regex('^(1|2|3|4|5)$'), self.handle_quantity_selection),
                    MessageHandler(filters.Regex('^Introdu cantitate manual$'), self.prompt_manual_quantity)
                ],
                self.GET_MANUAL_QUANTITY: [MessageHandler(filters.TEXT, self.handle_manual_quantity)],
                self.FINALIZE_ORDER: [MessageHandler(filters.Regex('^Finalizați comanda$'), self.handle_finalize_order)]

            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        ))
        application.add_handler(CommandHandler('qr', self.get_qr))
        application.add_handler(CommandHandler('menu', self.menu))
        application.add_handler(CommandHandler('info', self.info))
        application.add_handler(CallbackQueryHandler(self.menu_callback))
        application.add_handler(CallbackQueryHandler(self.handle_quantity_callback, pattern='^quantity_'))
        application.add_error_handler(self.error_handler)

        asyncio.run(application.run_polling())

    async def menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data

        # Log the received callback data
        self.logger.info(f"menu_callback received data: '{data}'")

        tg_user = update.effective_user
        user = await self.get_or_create_user(tg_user)

        # Handle quantity selection callbacks
        if data.startswith('quantity_'):
            quantity_str = data.split('_')[1]
            try:
                quantity = int(quantity_str)
                self.logger.info(f"Processing quantity: {quantity}")

                # Retrieve the selected product from user_data
                product = context.user_data.get('selected_product')
                if not product:
                    await query.message.reply_text("Eroare: produsul selectat nu a fost găsit.")
                    return ConversationHandler.END

                # Process the selected quantity
                await self.process_order_with_quantity(update, context, quantity)

                return ConversationHandler.END

            except ValueError:
                self.logger.warning(f"Invalid quantity value: {quantity_str}")
                await query.message.reply_text("Cantitate invalidă.")
                return self.GET_QUANTITY

        # Handle other callbacks (start, qr, info, etc.)
        if data == 'start':
            await self.start(update, context)
        elif data == 'qr':
            await self.get_qr(update, context)
        elif data == 'info':
            await self.info(update, context, edit_message=True)
        elif data.startswith('barista_menu'):
            await self.handle_barista_menu(update, context, user)
        elif data.startswith('category_'):
            await self.handle_category_selection(update, context, user, data)
        elif data.startswith('product_'):
            await self.handle_product_selection(update, context, user, data)
        elif data == 'add_more':
            await self.handle_add_more(update, context, user)
        elif data == 'checkout':
            await self.checkout_order(update, context)
        elif data == 'scan_qr':
            await self.prompt_scan_qr(update, context)
        elif data == 'anonymous_order':
            await self.create_anonymous_order(update, context)
        elif data == 'ignore':
            await query.answer()
        else:
            await query.edit_message_text(text="Opțiune selectată invalidă.")

    async def handle_barista_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user):
        query = update.callback_query

        if user.role != 'barista':
            await query.edit_message_text(text="Nu sunteți autorizat să accesați acest meniu.")
            return

        await self.show_categories(update, context)

    async def handle_finalize_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Retrieve the current order from the context
        order = context.user_data.get('current_order')
        if not order:
            await update.message.reply_text("Nu aveți nicio comandă în curs.")
            return ConversationHandler.END

        # Finalize the order (for example, save the order with status 'confirmed')
        order.status = 'confirmed'
        await sync_to_async(order.save)()

        # Clear the current order from the user's data
        context.user_data.pop('current_order', None)

        await update.message.reply_text(f"Comanda {order.session_name} a fost finalizată cu succes!")
        return ConversationHandler.END

    async def handle_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user, data: str):
        query = update.callback_query

        if user.role != 'barista':
            await query.edit_message_text(text="Nu sunteți autorizat să accesați acest meniu.")
            return

        try:
            # Extract category ID from callback data
            category_id = int(data.split('_')[1])
            category = await sync_to_async(Category.objects.get)(id=category_id)
            products = await sync_to_async(list)(category.products.all())

            if not products:
                await query.edit_message_text(text="Nu există produse în această categorie.")
                return

            # Create inline keyboard buttons for products
            keyboard = [
                [InlineKeyboardButton(f"{product.name} - {product.price} MDL", callback_data=f"product_{product.id}")]
                for product in products
            ]

            # Add navigation buttons
            keyboard.append([
                InlineKeyboardButton("Înapoi la categorii", callback_data='barista_menu'),
                InlineKeyboardButton("Finalizați comanda", callback_data='checkout'),
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=f"Produse în categoria {category.name}:",
                reply_markup=reply_markup
            )

        except (IndexError, ValueError):
            await query.edit_message_text(text="Identificator de categorie invalid.")
        except Category.DoesNotExist:
            await query.edit_message_text(text="Categoria selectată nu există.")

    async def handle_product_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user, data: str):
        query = update.callback_query

        if user.role != 'barista':
            await query.edit_message_text(text="Nu sunteți autorizat să accesați acest meniu.")
            return

        try:
            product_id = int(data.split('_')[1])
            product = await sync_to_async(Product.objects.get)(id=product_id)
            context.user_data['selected_product'] = product

            # Use InlineKeyboardMarkup for better button handling
            quantity_buttons = [
                [InlineKeyboardButton(f"{i}", callback_data=f"quantity_{i}") for i in range(1, 6)],
                [InlineKeyboardButton("Introdu cantitate manual", callback_data='manual_quantity')]
            ]
            reply_markup = InlineKeyboardMarkup(quantity_buttons)

            await query.edit_message_text(
                text=f"Ați selectat produsul: *{product.name}* - {product.price} MDL.\n"
                     f"Vă rugăm să selectați cantitatea dorită sau să o introduceți manual:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

            self.logger.info("Transitioning to GET_QUANTITY state")
            return self.GET_QUANTITY

        except (IndexError, ValueError):
            await query.edit_message_text(text="Identificator de produs invalid.")
        except Product.DoesNotExist:
            await query.edit_message_text(text="Produsul selectat nu există.")

    async def handle_quantity_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data

        # Log the callback data for debugging
        self.logger.info(f"Received callback data: {data}")

        if data.startswith('quantity_'):
            quantity_str = data.split('_')[1]
            try:
                quantity = int(quantity_str)
                await query.answer()  # Acknowledge the callback
                self.logger.info(f"Processing quantity: {quantity}")

                # Retrieve the selected product
                product = context.user_data.get('selected_product')
                if not product:
                    await query.message.reply_text("Eroare: produsul selectat nu a fost găsit.")
                    return ConversationHandler.END

                # Process the selected quantity
                await self.process_order_with_quantity(update, context, quantity)

                return ConversationHandler.END

            except ValueError:
                self.logger.warning(f"Invalid quantity value: {quantity_str}")
                await query.message.reply_text("Cantitate invalidă.")
                return self.GET_QUANTITY

        else:
            self.logger.error("Unexpected callback data.")
            await query.message.reply_text("Opțiune selectată invalidă.")

    async def handle_quantity_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text.strip()
        self.logger.info(f"Received quantity: '{message}'")

        # Retrieve the selected product
        product = context.user_data.get('selected_product')
        if not product:
            await update.message.reply_text("Eroare: produsul selectat nu a fost găsit.")
            return ConversationHandler.END

        try:
            # Parse the quantity
            quantity = int(message)
            if quantity <= 0:
                raise ValueError("Cantitatea trebuie să fie un număr pozitiv.")

            # Process the order with the selected quantity
            await self.process_order_with_quantity(update, context, quantity)
            return ConversationHandler.END

        except ValueError:
            # Handle invalid input and prompt again
            self.logger.warning(f"Invalid quantity input: {message}")
            await update.message.reply_text("Vă rugăm să introduceți un număr valid pentru cantitate.")
            return self.GET_QUANTITY

    async def prompt_manual_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Vă rugăm să introduceți cantitatea dorită:",
            reply_markup=ReplyKeyboardMarkup([[]], one_time_keyboard=True, resize_keyboard=True)  # Hides the keyboard
        )
        return self.GET_MANUAL_QUANTITY

    async def handle_manual_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message.text.strip()
        self.logger.info(f"handle_manual_quantity received input: '{message}'")

        try:
            quantity = int(message)
            if quantity <= 0:
                raise ValueError("Cantitatea trebuie să fie un număr pozitiv.")

            await self.process_order_with_quantity(update, context, quantity)
            return ConversationHandler.END

        except ValueError:
            await update.message.reply_text("Vă rugăm să introduceți un număr valid pentru cantitate.")
            return self.GET_MANUAL_QUANTITY

    async def process_order_with_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE, quantity: int):
        # Determine the chat to send messages
        if update.message:
            chat = update.message.chat
        elif update.callback_query:
            chat = update.callback_query.message.chat
        else:
            chat = update.effective_chat

        barista = await self.get_current_user(update)
        product = context.user_data.get('selected_product')

        if not product:
            await chat.send_message("Eroare: produsul selectat nu a fost găsit.")
            return

        # Assuming 'current_order' is used to track the ongoing order
        order = context.user_data.get('current_order')
        if not order:
            # Create a new order session
            session_name = f"Comanda_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            order = await sync_to_async(Order.objects.create)(
                user=None,  # To be set later if linked to a customer
                status='pending',
                session_name=session_name
            )
            context.user_data['current_order'] = order

        # Add or update product in the order
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

        # Log the order addition
        self.logger.info(
            f"Barista @{barista.username} added {quantity} x {product.name} to order {order.session_name}."
        )

        # Build the order summary
        order_items = await sync_to_async(list)(order.items.select_related('product').all())
        order_summary = '\n'.join([
            f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
            for item in order_items
        ])

        # Display options to add more or finalize the order
        keyboard = [
            ['Adăugați un alt produs'],
            ['Finalizați comanda']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await chat.send_message(
            text=f"Ați adăugat {quantity} x {product.name} la comanda curentă.\n\n"
                 f"Comanda curentă ({order.session_name}):\n{order_summary}\n\n"
                 "Doriți să adăugați un alt produs sau să finalizați comanda?",
            reply_markup=reply_markup
        )

        # Clear selected product from context
        context.user_data.pop('selected_product', None)

        return self.FINALIZE_ORDER

    async def handle_add_more(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user):
        query = update.callback_query

        if user.role != 'barista':
            await query.edit_message_text(text="Nu sunteți autorizat să adăugați produse.")
            return

        await self.show_categories(update, context)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles the /cancel command to exit conversations."""
        await update.message.reply_text('Operațiunea a fost anulată.',
                                        reply_markup=ReplyKeyboardMarkup([[]], one_time_keyboard=True,
                                                                         resize_keyboard=True))
        # Clear all user data related to the conversation
        context.user_data.clear()
        return ConversationHandler.END

    async def get_current_user(self, update: Update):
        """Helper method to retrieve the current user (barista)."""
        tg_user = update.effective_user
        user = await self.get_or_create_user(tg_user)
        return user

    async def get_or_create_user(self, tg_user):
        user, created = await sync_to_async(TgUser.objects.get_or_create)(
            user_id=tg_user.id,
            defaults={
                'username': tg_user.username,
                'first_name': tg_user.first_name,
                'role': 'barista' if tg_user.username in settings.BARISTA_USERNAMES else 'customer',
            }
        )
        return user

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_user = update.effective_user
        args = context.args

        if args:
            parameter = args[0]
            if parameter.startswith('create_order_'):
                customer_id = parameter[len('create_order_'):]
                barista = await self.get_or_create_user(tg_user)

                if barista.role != 'barista':
                    await update.effective_chat.send_message("Nu sunteți autorizat să creați comenzi.")
                    return

                try:
                    customer = await sync_to_async(TgUser.objects.get)(user_id=customer_id)
                    order_items = context.user_data.get('order_items', [])

                    if not order_items:
                        await update.effective_chat.send_message("Nu aveți produse în comandă.")
                        return

                    # Create orders for each item
                    for product in order_items:
                        await sync_to_async(Order.objects.create)(
                            user=customer,
                            item=product.name,
                            status='confirmed'
                        )

                    # Update purchase count
                    customer.purchase_count += len(order_items)
                    await sync_to_async(customer.save)()

                    # Build the order summary
                    order_summary = '\n'.join([
                        f"- {item.name} - {item.price} MDL"
                        for item in order_items
                    ])

                    # Notify the customer
                    purchases_left = (
                        self.PURCHASES_FOR_FREE_COFFEE - (customer.purchase_count % self.PURCHASES_FOR_FREE_COFFEE)
                        if customer.purchase_count % self.PURCHASES_FOR_FREE_COFFEE != 0 else 0
                    )
                    customer_message = (
                        f"🎉 Felicitări! Ați câștigat o cafea gratuită!\n\nComanda dumneavoastră:\n{order_summary}"
                        if purchases_left == 0 else
                        f"☕ Comanda dumneavoastră a fost servită!\n\nComanda:\n{order_summary}\n\n"
                        f"Mai aveți nevoie de {purchases_left} achiziție(i) pentru a primi o cafea gratuită."
                    )
                    await context.bot.send_message(chat_id=customer.user_id, text=customer_message)

                    # Notify the barista
                    await update.effective_chat.send_message(
                        f"Comanda pentru @{customer.username} a fost creată și confirmată."
                    )

                    # Clear the order items
                    context.user_data.pop('order_items', None)

                except TgUser.DoesNotExist:
                    await update.effective_chat.send_message("Clientul nu a fost găsit.")
                return
            else:
                await update.effective_chat.send_message("Comandă necunoscută.")
                return
        else:
            # Regular /start command
            user = await self.get_or_create_user(tg_user)
            message = (
                f"Bine ați venit, {tg_user.first_name}! Ați fost înregistrat."
                if user.purchase_count == 0 else
                f"Bine ați revenit, {tg_user.first_name}!"
            )
            await update.effective_chat.send_message(message)

    async def get_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message=False):
        tg_user = update.effective_user
        user = await self.get_or_create_user(tg_user)

        bot_username = context.bot.username
        customer_id = user.user_id
        parameter = f"create_order_{customer_id}"
        deep_link = f"https://t.me/{bot_username}?start={parameter}"

        # Generate the QR code asynchronously
        qr_img = await asyncio.to_thread(self.generate_qr_code, deep_link)

        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        buffer.seek(0)

        caption = "Aici este codul dumneavoastră QR unic. Prezentați-l baristei când comandați."

        if edit_message:
            query = update.callback_query
            await query.message.reply_photo(
                photo=InputFile(buffer, filename='qr_code.png'),
                caption=caption
            )
            await query.delete_message()
        else:
            await update.effective_chat.send_photo(
                photo=InputFile(buffer, filename='qr_code.png'),
                caption=caption
            )

    def generate_qr_code(self, data):
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        return qr.make_image(fill_color='black', back_color='white', image_factory=PilImage)

    async def info(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message=False):
        """
        Provides the user with their personal information and loyalty status.
        """
        tg_user = update.effective_user
        try:
            user = await sync_to_async(TgUser.objects.get)(user_id=tg_user.id)
            purchases_left = (
                self.PURCHASES_FOR_FREE_COFFEE - (user.purchase_count % self.PURCHASES_FOR_FREE_COFFEE)
                if user.purchase_count % self.PURCHASES_FOR_FREE_COFFEE != 0 else 0
            )
            loyalty_status = (
                "🎉 Aveți o cafea gratuită care vă așteaptă!"
                if purchases_left == 0 else
                f"Mai aveți nevoie de {purchases_left} achiziție(i) pentru a primi o cafea gratuită."
            )

            message = (
                f"👤 *Informațiile dumneavoastră:*\n\n"
                f"• *Nume:* {user.first_name}\n"
                f"• *Nume utilizator:* @{user.username}\n"
                f"• *ID Utilizator:* {user.user_id}\n"
                f"• *Număr achiziții:* {user.purchase_count}\n"
                f"• *Status loialitate:* {loyalty_status}"
            )

            if edit_message:
                query = update.callback_query
                await query.edit_message_text(message, parse_mode='Markdown')
            else:
                await update.effective_chat.send_message(message, parse_mode='Markdown')

        except TgUser.DoesNotExist:
            error_message = "Nu sunteți încă înregistrat. Vă rugăm să trimiteți /start pentru a vă înregistra."
            await update.effective_chat.send_message(error_message, parse_mode='Markdown')

    async def receive_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the reception of an item name from the barista during order creation.
        """
        barista_tg_user = update.effective_user
        barista = await self.get_or_create_user(barista_tg_user)

        if barista.role != 'barista':
            await update.effective_chat.send_message("Nu sunteți autorizat să creați comenzi.")
            return ConversationHandler.END

        item = update.message.text
        customer = context.user_data.get('customer')

        if not customer:
            await update.effective_chat.send_message("Datele clientului lipsesc.")
            return ConversationHandler.END

        await sync_to_async(Order.objects.create)(
            user=customer,
            item=item,
            status='confirmed'
        )
        customer.purchase_count += 1
        await sync_to_async(customer.save)()

        purchases_left = (
            self.PURCHASES_FOR_FREE_COFFEE - (customer.purchase_count % self.PURCHASES_FOR_FREE_COFFEE)
            if customer.purchase_count % self.PURCHASES_FOR_FREE_COFFEE != 0 else 0
        )
        customer_message = (
            f"🎉 Felicitări! Ați câștigat o cafea gratuită cu {item}!"
            if purchases_left == 0 else
            f"☕ {item} dumneavoastră a fost servit(ă)! Mai aveți nevoie de {purchases_left} achiziție(i) "
            "pentru a primi o cafea gratuită."
        )
        await context.bot.send_message(chat_id=customer.user_id, text=customer_message)

        await update.effective_chat.send_message(
            f"Comanda pentru @{customer.username} ({item}) a fost creată și confirmată."
        )

        return ConversationHandler.END

    async def receive_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the reception of the desired quantity for a selected product during order creation.
        """
        quantity_text = update.message.text

        # Log the received quantity input for debugging
        self.logger.info(f"Received quantity input: {quantity_text}")

        try:
            quantity = int(quantity_text)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Vă rugăm să introduceți un număr valid pentru cantitate.")
            return self.GET_QUANTITY

        product = context.user_data.get('selected_product')
        if not product:
            await update.message.reply_text("Eroare: produsul selectat nu a fost găsit.")
            return ConversationHandler.END

        # Log the selected product and quantity
        self.logger.info(f"Adding {quantity} of {product.name} to the order.")

        # Get or create the current order
        order = context.user_data.get('current_order')
        if not order:
            session_name = f"Comanda_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            order = await sync_to_async(Order.objects.create)(
                user=None,  # Will be set later if customer is known
                status='pending',
                session_name=session_name
            )
            context.user_data['current_order'] = order

        # Add or update product in the order
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

        # Build the order summary
        order_items = await sync_to_async(list)(order.items.select_related('product').all())
        order_summary = '\n'.join([
            f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
            for item in order_items
        ])

        # Display options to add more or finalize the order
        quantity_options = ['1', '2', '3', '4', '5']
        keyboard = [
            quantity_options,
            ['Introdu cantitate manual']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            text=f"Ați adăugat {quantity} x {product.name} la comanda curentă.\n\n"
                 f"Comanda curentă ({order.session_name}):\n{order_summary}\n\n"
                 "Doriți să adăugați un alt produs sau să finalizați comanda?",
            reply_markup=reply_markup
        )

        # Clear selected product from context
        context.user_data.pop('selected_product', None)

        return ConversationHandler.END

    async def checkout_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the checkout process, allowing the barista to scan a customer's QR code or proceed anonymously.
        """
        query = update.callback_query

        # Build the current order summary
        order = context.user_data.get('current_order')
        if not order:
            await query.edit_message_text("Nu aveți produse în comandă. Vă rugăm să adăugați produse mai întâi.")
            return

        # Retrieve order items
        order_items = await sync_to_async(list)(order.items.select_related('product').all())
        if not order_items:
            await query.edit_message_text("Nu aveți produse în comandă. Vă rugăm să adăugați produse mai întâi.")
            return

        order_summary = '\n'.join([
            f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
            for item in order_items
        ])

        # Present options to scan QR code or proceed anonymously
        keyboard = [
            [InlineKeyboardButton("Scanați codul QR al clientului", callback_data='scan_qr')],
            [InlineKeyboardButton("Comandă anonimă", callback_data='anonymous_order')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=f"Comanda curentă:\n{order_summary}\n\n"
                 "Doriți să scanați codul QR al clientului sau să finalizați comanda anonim?",
            reply_markup=reply_markup
        )

    async def prompt_scan_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Prompts the barista to scan the customer's QR code to associate the order with the customer.
        """
        query = update.callback_query

        await query.edit_message_text(
            text="Vă rugăm să scanați codul QR al clientului pentru a finaliza comanda."
        )

    async def create_anonymous_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Finalizes an anonymous order without associating it with any customer.
        """
        query = update.callback_query

        order = context.user_data.get('current_order')
        if not order:
            await query.edit_message_text("Nu aveți o comandă în curs.")
            return

        # Update order status
        order.status = 'confirmed'
        await sync_to_async(order.save)()

        # Build the order summary
        order_items = await sync_to_async(list)(order.items.select_related('product').all())
        order_summary = '\n'.join([
            f"- {item.product.name} - {item.product.price} MDL x {item.quantity}"
            for item in order_items
        ])

        # Notify the barista
        await query.edit_message_text(
            text=f"Comandă anonimă ({order.session_name}) a fost creată cu succes.\n\nComanda:\n{order_summary}"
        )

        # Clear the order from context
        context.user_data.pop('current_order', None)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Logs errors and notifies the developer/admin.
        """
        self.logger.error(f"Update {update} caused error {context.error}")
        # Optionally, notify the admin or developer about the error
        # await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Error: {context.error}")

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Displays the main menu based on the user's role.
        """
        tg_user = update.effective_user
        user = await self.get_or_create_user(tg_user)
        reply_markup = self.get_keyboard(user.role)

        await update.message.reply_text(
            "Vă rugăm să alegeți o opțiune:",
            reply_markup=reply_markup
        )

    async def get_or_create_user(self, tg_user):
        """
        Retrieves an existing TgUser or creates a new one based on the Telegram user information.
        """
        user, created = await sync_to_async(TgUser.objects.get_or_create)(
            user_id=tg_user.id,
            defaults={
                'username': tg_user.username,
                'first_name': tg_user.first_name,
                'role': 'customer',
            }
        )
        return user

    async def show_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Displays all available categories to the barista.
        """
        query = update.callback_query

        # Get all categories
        categories = await sync_to_async(list)(Category.objects.all())

        if not categories:
            await query.edit_message_text("Nu există categorii disponibile.")
            return

        # Create inline keyboard buttons for categories
        keyboard = [
            [InlineKeyboardButton(category.name, callback_data=f"category_{category.id}")]
            for category in categories
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="Selectați o categorie:",
            reply_markup=reply_markup
        )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the /cancel command to exit conversations gracefully.
        """
        if update.message:
            await update.message.reply_text('Operațiunea a fost anulată.', reply_markup=InlineKeyboardMarkup([]))
        elif update.callback_query:
            await update.callback_query.edit_message_text(text='Operațiunea a fost anulată.',
                                                          reply_markup=InlineKeyboardMarkup([]))
        return ConversationHandler.END
