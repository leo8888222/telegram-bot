# Bot v5.0 - Universal AI Assistant with fixed API calls
import logging
import os
import sys
import time
import urllib.request
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

TOKEN = "8865814143:AAGLAlitGSVH3MnkngGCisosPj9EHlEndIA"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "sk-nDATqELoAhSqTiPaTHeDdx")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.manus.im/api/llm-proxy/v1")

def force_claim_bot():
    """Delete webhook and clear update queue to force claim polling rights"""
    base_url = f"https://api.telegram.org/bot{TOKEN}"
    try:
        req = urllib.request.Request(f"{base_url}/deleteWebhook?drop_pending_updates=true")
        urllib.request.urlopen(req, timeout=10)
        req = urllib.request.Request(f"{base_url}/getUpdates?limit=1&timeout=1")
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        if data.get("result"):
            offset = data["result"][-1]["update_id"] + 1
            req = urllib.request.Request(f"{base_url}/getUpdates?offset={offset}&limit=1&timeout=1")
            urllib.request.urlopen(req, timeout=15)
        logger.info("Successfully claimed bot polling rights")
    except Exception as e:
        logger.warning(f"Force claim attempt: {e}")

SYSTEM_PROMPT = """你是一个超级智能AI助手，名叫Leo助手。你像一个全能的技术专家和生活顾问。

你的能力包括但不限于：
- 编程开发：Python、JavaScript、HTML/CSS、小程序开发、App开发、网站开发等所有编程语言
- 软件开发：能帮用户设计架构、写代码、调试bug、解释代码
- 数据分析：Excel处理、数据可视化、统计分析
- AI和机器学习：模型训练、算法设计
- 文案写作：各种风格的文章、营销文案、翻译
- 商业咨询：创业建议、市场分析、商业计划
- 生活助手：旅行规划、学习建议、问题解答
- 数学计算：各种数学问题
- 创意设计：UI设计建议、产品设计思路

你的回答风格：
- 专业但易懂，用中文回答（除非用户用其他语言提问）
- 如果用户问编程问题，直接给出可运行的代码
- 回答要详细、有条理
- 像一个耐心的朋友一样交流
- 不要拒绝任何合理的请求

你不是一个外贸机器人，你是一个万能AI助手，什么都能帮忙！"""

conversation_history = {}

def get_ai_response(user_id, user_message):
    """Call AI API with proper parameters"""
    try:
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        if len(conversation_history[user_id]) > 20:
            conversation_history[user_id] = conversation_history[user_id][-20:]
        conversation_history[user_id].append({"role": "user", "content": user_message})
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[user_id]
        
        # Use urllib to call the API directly
        url = f"{OPENAI_API_BASE}/chat/completions"
        payload = json.dumps({
            "model": "gpt-5-nano",
            "messages": messages,
            "max_completion_tokens": 2000,
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        })
        
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        
        assistant_message = data["choices"][0]["message"].get("content")
        
        if not assistant_message:
            assistant_message = "抱歉，我没能生成回复，请再试一次。"
        
        conversation_history[user_id].append({"role": "assistant", "content": assistant_message})
        return assistant_message
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return f"抱歉，我暂时遇到了一点问题，请稍后再试。\n错误信息：{str(e)[:100]}"

async def start(update, context):
    user = update.effective_user
    welcome_text = (
        f"你好 {user.first_name}！👋\n\n"
        "我是Leo助手，一个超级智能AI机器人！\n\n"
        "我能帮你做的事情：\n"
        "💻 编程开发（Python、小程序、网站等）\n"
        "📝 写文案、翻译\n"
        "📊 数据分析\n"
        "💡 创意和设计建议\n"
        "🧮 数学计算\n"
        "🤖 AI和技术问题\n"
        "📚 学习辅导\n"
        "🏢 商业咨询\n\n"
        "直接发消息给我，问什么都行！\n\n"
        "命令：\n"
        "/clear - 清除对话记录\n"
        "/help - 查看帮助"
    )
    keyboard = [
        [InlineKeyboardButton("💻 编程帮助", callback_data="coding")],
        [InlineKeyboardButton("📝 写作帮助", callback_data="writing")],
        [InlineKeyboardButton("💡 创意灵感", callback_data="creative")]
    ]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update, context):
    text = (
        "📖 使用帮助\n\n"
        "直接给我发消息就行，我能理解你说的任何话！\n\n"
        "示例：\n"
        "• 帮我写一个Python爬虫\n"
        "• 帮我做一个微信小程序的登录页面\n"
        "• 解释一下什么是机器学习\n"
        "• 帮我写一封英文邮件\n"
        "• 1000元怎么理财\n\n"
        "命令：\n"
        "/start - 重新开始\n"
        "/clear - 清除对话记录\n"
        "/help - 查看帮助"
    )
    await update.message.reply_text(text)

async def clear_history(update, context):
    user_id = update.effective_user.id
    if user_id in conversation_history:
        del conversation_history[user_id]
    await update.message.reply_text("✅ 对话记录已清除！可以开始新的对话了。")

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "coding":
        await query.message.reply_text("你想做什么程序？告诉我需求，我帮你写代码！比如：\n• 网站\n• 小程序\n• Python脚本\n• App\n• 游戏")
    elif data == "writing":
        await query.message.reply_text("需要写什么？比如：\n• 文章/博客\n• 营销文案\n• 邮件\n• 翻译\n• 简历")
    elif data == "creative":
        await query.message.reply_text("需要什么创意？比如：\n• 产品设计思路\n• UI界面建议\n• 商业点子\n• 活动策划")

async def handle_message(update, context):
    user_id = update.effective_user.id
    user_message = update.message.text
    await update.message.chat.send_action("typing")
    ai_response = get_ai_response(user_id, user_message)
    # Telegram has a 4096 char limit per message
    if len(ai_response) > 4000:
        parts = [ai_response[i:i+4000] for i in range(0, len(ai_response), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(ai_response)

def main():
    logger.info("Forcing claim of bot polling rights...")
    force_claim_bot()
    time.sleep(2)
    force_claim_bot()
    time.sleep(3)
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("AI-powered bot v5.0 started successfully!")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
