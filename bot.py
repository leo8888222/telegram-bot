#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leo助手 v7.0 — 更聪明、不断联的 Telegram AI 机器人
"""
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.error import Conflict, NetworkError, TimedOut, RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from openai import AsyncOpenAI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("leo-bot")

_LEGACY_TOKEN = "8865814143:AAGLAlitGSVH3MnkngGCisosPj9EHlEndIA"
TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or _LEGACY_TOKEN
)
if TOKEN == _LEGACY_TOKEN:
    logger.warning("正在使用写死在代码里的 Bot Token！请尽快更换。")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "<redacted>")
OPENAI_API_BASE = os.environ.get(
    "OPENAI_API_BASE", "https://api.manus.im/api/llm-proxy/v1"
)
DEFAULT_MODEL = os.environ.get("AI_MODEL", "gpt-5-mini")

STATE_FILE = Path(os.environ.get("BOT_STATE_FILE", "bot_state.json"))
MAX_HISTORY = 30
AI_TIMEOUT = 60
AI_MAX_RETRIES = 3
TG_MSG_LIMIT = 4000

START_TIME = time.time()

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

_state = {"users": {}}


def _blank_user():
    return {"messages": [], "model": DEFAULT_MODEL}


def get_user_state(user_id: int) -> dict:
    return _state["users"].setdefault(str(user_id), _blank_user())


def load_state():
    global _state
    try:
        if STATE_FILE.exists():
            _state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _state.setdefault("users", {})
            logger.info(f"已从 {STATE_FILE} 恢复 {len(_state['users'])} 位用户的对话记录")
    except Exception as e:
        logger.warning(f"读取状态文件失败，将从空状态启动: {e}")
        _state = {"users": {}}


def save_state():
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as e:
        logger.warning(f"保存状态文件失败: {e}")


_ai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE, timeout=AI_TIMEOUT
)


async def get_ai_response(user_id: int, user_message: str) -> str:
    ustate = get_user_state(user_id)
    model = ustate.get("model") or DEFAULT_MODEL

    ustate["messages"].append({"role": "user", "content": user_message})
    if len(ustate["messages"]) > MAX_HISTORY:
        ustate["messages"] = ustate["messages"][-MAX_HISTORY:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + ustate["messages"]

    last_err = None
    for attempt in range(1, AI_MAX_RETRIES + 1):
        try:
            resp = await _ai_client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=2000,
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                text = "抱歉，我没能生成回复，请再试一次。"
            ustate["messages"].append({"role": "assistant", "content": text})
            if len(ustate["messages"]) > MAX_HISTORY:
                ustate["messages"] = ustate["messages"][-MAX_HISTORY:]
            save_state()
            return text
        except Exception as e:
            last_err = e
            logger.warning(f"AI 请求第 {attempt}/{AI_MAX_RETRIES} 次失败 "
                           f"({type(e).__name__}): {e}")
            if attempt < AI_MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    if ustate["messages"] and ustate["messages"][-1].get("role") == "user":
        ustate["messages"].pop()
    save_state()
    return f"抱歉，AI 服务暂时不可用，请稍后再试。\n（{type(last_err).__name__}）"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "/model - 查看/切换 AI 模型\n"
        "/remind - 定时提醒（例：/remind 10m 喝水）\n"
        "/status - 查看运行状态\n"
        "/clear - 清除对话记录\n"
        "/help - 查看帮助"
    )
    keyboard = [
        [InlineKeyboardButton("💻 编程帮助", callback_data="coding")],
        [InlineKeyboardButton("📝 写作帮助", callback_data="writing")],
        [InlineKeyboardButton("💡 创意灵感", callback_data="creative")],
    ]
    await update.message.reply_text(
        welcome_text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "/model - 查看/切换 AI 模型\n"
        "/remind 10m 内容 - 定时提醒（s/m/h/d）\n"
        "/status - 查看运行状态\n"
        "/clear - 清除对话记录\n"
        "/help - 查看帮助"
    )
    await update.message.reply_text(text)


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _state["users"].pop(str(update.effective_user.id), None)
    save_state()
    await update.message.reply_text("✅ 对话记录已清除！可以开始新的对话了。")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ustate = get_user_state(update.effective_user.id)
    args = context.args
    if not args:
        await update.message.reply_text(
            f"当前模型：`{ustate.get('model') or DEFAULT_MODEL}`\n\n"
            "切换模型：`/model 模型名`\n例如：`/model gpt-5`",
            parse_mode="Markdown",
        )
        return
    new_model = args[0].strip()
    ustate["model"] = new_model
    save_state()
    await update.message.reply_text(
        f"✅ 已切换到模型：`{new_model}`", parse_mode="Markdown"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - START_TIME)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    ustate = get_user_state(update.effective_user.id)
    token_src = "环境变量 ✅" if TOKEN != _LEGACY_TOKEN else "代码内置 ⚠️（请尽快更换！）"
    await update.message.reply_text(
        "🤖 Leo助手运行状态\n\n"
        f"⏱ 已运行：{h}小时{m}分{s}秒\n"
        f"🧠 当前模型：{ustate.get('model') or DEFAULT_MODEL}\n"
        f"💬 你的上下文消息数：{len(ustate['messages'])}\n"
        f"👥 已记录用户数：{len(_state['users'])}\n"
        f"🔑 Token 来源：{token_src}"
    )


_DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "用法：`/remind 10m 喝水`\n时间单位：s 秒 / m 分 / h 小时 / d 天",
            parse_mode="Markdown",
        )
        return
    m = _DURATION_RE.match(args[0])
    if not m:
        await update.message.reply_text(
            "时间格式不对，例子：`/remind 30m 开会`", parse_mode="Markdown"
        )
        return
    seconds = int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]
    if seconds > 30 * 86400:
        await update.message.reply_text("提醒时间太长了，最多支持 30 天。")
        return
    text = " ".join(args[1:])
    chat_id = update.effective_chat.id

    async def _reminder():
        await asyncio.sleep(seconds)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ 提醒：{text}")
        except Exception as e:
            logger.warning(f"发送提醒失败: {e}")

    asyncio.create_task(_reminder())
    await update.message.reply_text(
        f"✅ 好的，{args[0]} 后提醒你：{text}\n（注：机器人重启后还没触发的提醒会丢失）"
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "coding":
        await query.message.reply_text(
            "你想做什么程序？告诉我需求，我帮你写代码！比如：\n"
            "• 网站\n• 小程序\n• Python脚本\n• App\n• 游戏"
        )
    elif data == "writing":
        await query.message.reply_text(
            "需要写什么？比如：\n• 文章/博客\n• 营销文案\n• 邮件\n• 翻译\n• 简历"
        )
    elif data == "creative":
        await query.message.reply_text(
            "需要什么创意？比如：\n• 产品设计思路\n• UI界面建议\n• 商业点子\n• 活动策划"
        )


async def send_long_text(update: Update, text: str):
    if len(text) <= TG_MSG_LIMIT:
        await update.message.reply_text(text)
        return
    chunks, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > TG_MSG_LIMIT:
            chunks.append(buf)
            buf = line
        else:
            buf = buf + "\n" + line if buf else line
    if buf:
        chunks.append(buf)
    for c in chunks:
        for i in range(0, len(c), TG_MSG_LIMIT):
            await update.message.reply_text(c[i:i + TG_MSG_LIMIT])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except Exception:
        pass
    ai_response = await get_ai_response(user_id, user_message)
    await send_long_text(update, ai_response)


async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("我目前主要处理文字消息哦，直接发文字给我就行 🙂")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("处理更新时出错", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "😵 出了点小问题，我已记录，稍后再试试吧。"
            )
    except Exception:
        pass


async def post_init(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=False)
        me = await app.bot.get_me()
        logger.info(f"Bot 已上线：@{me.username}（轮询模式，保留待处理消息）")
    except Exception as e:
        logger.warning(f"post_init 失败: {e}")


def build_app() -> Application:
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    app.add_error_handler(error_handler)
    return app


def main():
    load_state()
    logger.info("Leo助手 v7.0 启动（守护模式）")
    backoff = 10
    while True:
        try:
            app = build_app()
            app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
            logger.warning("run_polling 意外退出，10 秒后重启")
            time.sleep(10)
            backoff = 10
        except Conflict:
            logger.warning("轮询冲突 409：另一实例正在运行，60 秒后重试（不丢消息）")
            time.sleep(60)
        except RetryAfter as e:
            wait = int(getattr(e, "retry_after", 30)) + 5
            logger.warning(f"被 Telegram 限流，等待 {wait} 秒")
            time.sleep(wait)
        except (NetworkError, TimedOut) as e:
            logger.warning(f"网络问题 ({type(e).__name__})，{backoff} 秒后重试")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except KeyboardInterrupt:
            logger.info("收到退出信号，Bye 👋")
            break
        except Exception:
            logger.exception(f"未知错误，{backoff} 秒后重启")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    main()
