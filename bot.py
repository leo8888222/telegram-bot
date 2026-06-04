import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Token
TOKEN = os.environ.get("BOT_TOKEN", "8865814143:AAHZdZhwGew4C2D_IgcpUhsN25jqYwVdLkg")

# FAQ Data
FAQ_DATA = {
    "product_intro": "We provide high-quality industrial components and consumer electronics. All products are CE/RoHS certified.",
    "price": "Our pricing is competitive and depends on the order volume. Please use /inquiry to get a specific quote.",
    "moq": "Minimum Order Quantity (MOQ) varies by product, generally starting from 100 units.",
    "lead_time": "Standard lead time is 7-15 days for stock items and 30-45 days for OEM orders.",
    "payment": "We accept T/T, L/C, Western Union, and Alibaba Trade Assurance."
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_text = (
        f"Hello {user.first_name}! 👋\n\n"
        f"Welcome to Leo's Foreign Trade Service. I am your automated assistant.\n"
        f"How can I help you today?\n\n"
        "Available Commands:\n"
        "/products - View our product catalog\n"
        "/inquiry - Send a business inquiry\n"
        "/contact - Get contact information\n"
        "/faq - Common questions"
    )
    
    keyboard = [
        [InlineKeyboardButton("📦 Products", callback_data="view_products")],
        [InlineKeyboardButton("📝 Send Inquiry", callback_data="start_inquiry")],
        [InlineKeyboardButton("❓ FAQ", callback_data="view_faq")],
        [InlineKeyboardButton("📞 Contact Leo", callback_data="view_contact")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📂 Product Catalog (Sample)\n\n"
        "1. Model A-100: High-efficiency sensor\n"
        "2. Model B-200: Industrial controller\n"
        "3. Model C-300: Smart wireless module\n\n"
        "Please select a category or contact us for the full PDF catalog."
    )
    keyboard = [
        [InlineKeyboardButton("Request PDF Catalog", callback_data="req_catalog")],
        [InlineKeyboardButton("Back to Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👤 Contact Information\n\n"
        "Manager: Leo\n"
        "Email: leo@example.com\n"
        "WhatsApp: +86 123 4567 8910\n"
        "WeChat: LeoTrade88\n\n"
        "Feel free to reach out for urgent matters!"
    )
    keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def faq_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "❓ Frequently Asked Questions\nSelect a topic to learn more:"
    keyboard = [
        [InlineKeyboardButton("Product Intro", callback_data="faq_product_intro")],
        [InlineKeyboardButton("Pricing", callback_data="faq_price")],
        [InlineKeyboardButton("MOQ", callback_data="faq_moq")],
        [InlineKeyboardButton("Lead Time", callback_data="faq_lead_time")],
        [InlineKeyboardButton("Payment Methods", callback_data="faq_payment")],
        [InlineKeyboardButton("Back to Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "view_products":
        await products(update, context)
    elif data == "view_faq":
        await faq_menu(update, context)
    elif data == "view_contact":
        await contact(update, context)
    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("📦 Products", callback_data="view_products")],
            [InlineKeyboardButton("📝 Send Inquiry", callback_data="start_inquiry")],
            [InlineKeyboardButton("❓ FAQ", callback_data="view_faq")],
            [InlineKeyboardButton("📞 Contact Leo", callback_data="view_contact")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("How can I help you today?", reply_markup=reply_markup)
    elif data.startswith("faq_"):
        key = data.replace("faq_", "")
        faq_text = f"💡 {key.replace('_', ' ').title()}\n\n{FAQ_DATA.get(key, 'No information available.')}"
        keyboard = [[InlineKeyboardButton("Back to FAQ", callback_data="view_faq")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(faq_text, reply_markup=reply_markup)
    elif data == "req_catalog":
        await query.message.reply_text("Our team will send the catalog to you shortly. Please make sure you've provided your contact info via /inquiry.")
    elif data == "start_inquiry":
        await query.message.reply_text("Let's collect your inquiry details. What is your full name?", reply_markup=ReplyKeyboardRemove())
        context.user_data["in_inquiry"] = True
        context.user_data["inquiry_step"] = "name"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("in_inquiry"):
        step = context.user_data.get("inquiry_step")
        if step == "name":
            context.user_data["name"] = update.message.text
            context.user_data["inquiry_step"] = "country"
            await update.message.reply_text(f"Nice to meet you, {update.message.text}! Which country are you from?")
        elif step == "country":
            context.user_data["country"] = update.message.text
            context.user_data["inquiry_step"] = "product"
            await update.message.reply_text("Which product are you interested in?")
        elif step == "product":
            context.user_data["product"] = update.message.text
            context.user_data["inquiry_step"] = "quantity"
            await update.message.reply_text("What is the estimated quantity you need?")
        elif step == "quantity":
            context.user_data["quantity"] = update.message.text
            summary = (
                "✅ Inquiry Received!\n\n"
                f"Name: {context.user_data['name']}\n"
                f"Country: {context.user_data['country']}\n"
                f"Product: {context.user_data['product']}\n"
                f"Quantity: {context.user_data['quantity']}\n\n"
                "Leo will contact you shortly with a formal quote. Thank you!"
            )
            await update.message.reply_text(summary)
            context.user_data["in_inquiry"] = False
            context.user_data["inquiry_step"] = None
            logger.info(f"New Inquiry: {context.user_data}")
    else:
        text = (
            "Thank you for your message! 😊\n\n"
            "I'm Leo's trade assistant. Here's what I can help with:\n"
            "/products - View our catalog\n"
            "/inquiry - Send an inquiry\n"
            "/contact - Contact Leo directly\n"
            "/faq - Common questions\n\n"
            "Or just tap a button below:"
        )
        keyboard = [
            [InlineKeyboardButton("📦 Products", callback_data="view_products")],
            [InlineKeyboardButton("📝 Send Inquiry", callback_data="start_inquiry")],
            [InlineKeyboardButton("📞 Contact Leo", callback_data="view_contact")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)

async def inquiry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["in_inquiry"] = True
    context.user_data["inquiry_step"] = "name"
    await update.message.reply_text("Let's collect your inquiry details. What is your full name?")

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("products", products))
    application.add_handler(CommandHandler("contact", contact))
    application.add_handler(CommandHandler("faq", faq_menu))
    application.add_handler(CommandHandler("inquiry", inquiry_command))
    
    # Callback Query Handler
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the Bot
    logger.info("Bot started successfully!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
