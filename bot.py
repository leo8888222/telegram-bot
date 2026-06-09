import logging
import os
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.manus.im/api/llm-proxy/v1")

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

SYSTEM_PROMPT = """You are Leo's intelligent foreign trade assistant. You work for Leo, a professional foreign trade businessman based in Jincheng, China.

Your capabilities:
- Answer any questions about foreign trade, products, shipping, payment methods, etc.
- Communicate fluently in multiple languages (English, Chinese, Spanish, Arabic, etc.)
- Help customers understand products, pricing, MOQ, lead times
- Provide professional trade advice
- Be friendly, helpful, and professional

Key information about Leo's business:
- Based in Jincheng, Shanxi, China
- Specializes in high-quality Chinese manufactured products
- Competitive pricing with flexible MOQ
- Standard lead time: 7-15 days for stock, 30-45 days for OEM
- Payment: T/T, L/C, Western Union, PayPal
- Contact: Leo (WeChat: LeoTrade88)

Always be helpful, professional, and try to convert inquiries into orders."""

conversation_history = {}

def get_ai_response(user_id, user_message):
    try:
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        if len(conversation_history[user_id]) > 20:
            conversation_history[user_id] = conversation_history[user_id][-20:]
        conversation_history[user_id].append({"role": "user", "content": user_message})
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *conversation_history[user_id]],
            max_tokens=1000,
            temperature=0.7,
        )
        assistant_message = response.choices[0].message.content
        conversation_history[user_id].append({"role": "assistant", "content": assistant_message})
        return assistant_message
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return "Sorry, I'm having a temporary issue. Please try again or use /contact to reach Leo directly."

async def start(update, context):
    user = update.effective_user
    welcome_text = (
        f"Hello {user.first_name}! 👋\n\n"
        "Welcome to Leo's Foreign Trade Service. I am an AI-powered assistant.\n"
        "You can ask me anything! I understand multiple languages.\n\n"
        "/products - Product catalog\n"
        "/inquiry - Send inquiry\n"
        "/contact - Contact Leo\n"
        "/clear - Clear chat history\n\n"
        "Or just type your question!"
    )
    keyboard = [
        [InlineKeyboardButton("📦 Products", callback_data="view_products")],
        [InlineKeyboardButton("📝 Send Inquiry", callback_data="start_inquiry")],
        [InlineKeyboardButton("📞 Contact Leo", callback_data="view_contact")]
    ]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def products(update, context):
    text = "📂 We offer many product categories. Just ask me about any specific product!"
    keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="main_menu")]]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def contact(update, context):
    text = "👤 Contact:\nManager: Leo\nWeChat: LeoTrade88\nWhatsApp: +86 123 4567 8910"
    keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="main_menu")]]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def clear_history(update, context):
    user_id = update.effective_user.id
    if user_id in conversation_history:
        del conversation_history[user_id]
    await update.message.reply_text("✅ History cleared!")

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "view_products":
        await products(update, context)
    elif data == "view_contact":
        await contact(update, context)
    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("📦 Products", callback_data="view_products")],
            [InlineKeyboardButton("📝 Send Inquiry", callback_data="start_inquiry")],
            [InlineKeyboardButton("📞 Contact Leo", callback_data="view_contact")]
        ]
        await query.message.edit_text("How can I help you?", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "start_inquiry":
        await query.message.reply_text("Tell me what products you need, quantity, and any requirements!")

async def handle_message(update, context):
    user_id = update.effective_user.id
    user_message = update.message.text
    await update.message.chat.send_action("typing")
    ai_response = get_ai_response(user_id, user_message)
    await update.message.reply_text(ai_response)

async def inquiry_command(update, context):
    await update.message.reply_text("Tell me what you're looking for and I'll help!")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("products", products))
    application.add_handler(CommandHandler("contact", contact))
    application.add_handler(CommandHandler("inquiry", inquiry_command))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("AI-powered bot started!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
