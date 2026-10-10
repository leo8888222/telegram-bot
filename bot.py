#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leo助手 v8.0 — 改用 Manus 官方 Task API

v8.0 变更:
- 放弃 manus.im llm-proxy（其 sandbox token 无法从外部续期），改用 Manus 官方 API
- 每个 Telegram 用户对应一个 Manus task，通过 task.sendMessage 保持对话上下文
- 异步轮询 task.listMessages 获取回复
- 保留 v7.0 的全部 Telegram 健壮性：守护重启、409 冲突等待、状态持久化等
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.error import Conflict, NetworkError, TimedOut, RetryAfter, InvalidToken
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("leo-bot")

# ================= 配置 =================
# Bot Token 必须通过环境变量提供（GitHub Secrets / Fly secrets），代码中不再硬编码
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or ""
if not TOKEN:
    raise SystemExit(
        "缺少 Telegram Bot Token！请设置 TELEGRAM_BOT_TOKEN 环境变量。"
    )

# Manus 官方 API（https://open.manus.ai/docs）
MANUS_API_KEY = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("MANUS_API_KEY", "")
MANUS_API_BASE = "https://api.manus.ai"
DEFAULT_PROFILE = os.environ.get("AI_MODEL", "manus-1.6-lite")  # 可选: manus-1.6 / manus-1.6-lite / manus-1.6-max

STATE_FILE = Path(os.environ.get("BOT_STATE_FILE", "bot_state.json"))
AI_TIMEOUT = 30
POLL_INTERVAL = 3          # 轮询 Manus 回复的间隔（秒）
POLL_MAX_WAIT = 180        # 单条消息最长等待（秒）
TG_MSG_LIMIT = 4000

START_TIME = time.time()

SYSTEM_PROMPT = """你是一个超级智能AI助手，名叫Leo助手。你像一个全能的技术专家和生活顾问。

你的能力包括但不限于：
- 编程开发：Python、JavaScript、HTML/CSS、小程序开发、App开发、网站开发等所有编程语言
- 数据分析、AI和机器学习、文案写作、商业咨询、生活助手、数学计算、创意设计

你的回答风格：
- 专业但易懂，用中文回答（除非用户用其他语言提问）
- 如果用户问编程问题，直接给出可运行的代码
- 回答要详细、有条理
- 像一个耐心的朋友一样交流
- 回答尽量简洁有力，适合在 Telegram 手机端阅读（除非用户要求详细展开）
- 不要拒绝任何合理的请求

你不是一个外贸机器人，你是一个万能AI助手，什么都能帮忙！"""


# ================= 持久化状态 =================
_state = {"users": {}}  # user_id(str) -> {"manus_task_id": str, "profile": str}


def _blank_user():
    return {"manus_task_id": "", "profile": DEFAULT_PROFILE}


def get_user_state(user_id: int) -> dict:
    return _state["users"].setdefault(str(user_id), _blank_user())


def load_state():
    global _state
    try:
        if STATE_FILE.exists():
            _state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _state.setdefault("users", {})
            logger.info(f"已从 {STATE_FILE} 恢复 {len(_state['users'])} 位用户的状态")
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


# ================= Manus Task API =================
def _headers():
    return {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}


async def _manus_post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    r = await client.post(f"{MANUS_API_BASE}{path}", headers=_headers(), json=payload)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Manus API 返回 ok=false: {data}")
    return data


async def _manus_get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    r = await client.get(f"{MANUS_API_BASE}{path}", headers=_headers(), params=params)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Manus API 返回 ok=false: {data}")
    return data


def _extract_assistant_text(messages: list, after_ts: int) -> str | None:
    """从 listMessages 结果中找时间戳晚于 after_ts 的最新 assistant 回复。"""
    for m in messages:
        if m.get("type") != "assistant_message":
            continue
        try:
            ts = int(m.get("timestamp", 0))
        except (ValueError, TypeError):
            ts = 0
        if ts <= after_ts:
            continue
        content = (m.get("assistant_message") or {}).get("content", "")
        if content and content.strip():
            return content.strip()
    return None


async def _wait_for_reply(client: httpx.AsyncClient, task_id: str, after_ts: int) -> str:
    """轮询直到拿到新的 assistant 回复或超时。"""
    deadline = time.time() + POLL_MAX_WAIT
    last_log = 0
    while time.time() < deadline:
        try:
            data = await _manus_get(
                client, "/v2/task.listMessages",
                {"task_id": task_id, "order": "desc", "limit": 10},
            )
            text = _extract_assistant_text(data.get("messages", []), after_ts)
            if text:
                return text
        except Exception as e:
            logger.warning(f"轮询 Manus 消息失败: {e}")
        if time.time() - last_log > 30:
            logger.info(f"等待 Manus 回复中 task={task_id} ...")
            last_log = time.time()
        await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError("等待 Manus 回复超时")


async def get_ai_response(user_id: int, user_message: str) -> str:
    if not MANUS_API_KEY:
        return "AI 服务未配置（缺少 API Key），请联系管理员。"

    ustate = get_user_state(user_id)
    profile = ustate.get("profile") or DEFAULT_PROFILE
    task_id = ustate.get("manus_task_id") or ""

    # 发送时间戳（毫秒），用于识别"新"回复
    after_ts = int(time.time() * 1000)

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            if not task_id:
                # 首次：创建 task，把系统提示词拼在第一条消息前面
                first_content = (
                    f"[系统指令：{SYSTEM_PROMPT}]\n\n[用户消息]\n{user_message}"
                )
                data = await _manus_post(client, "/v2/task.create", {
                    "message": {"content": first_content},
                    "agent_profile": profile,
                    "locale": "zh-CN",
                    "hide_in_task_list": True,
                    "share_visibility": "private",
                })
                task_id = data["task_id"]
                ustate["manus_task_id"] = task_id
                save_state()
                logger.info(f"为用户 {user_id} 创建 Manus task: {task_id}")
            else:
                # 后续：向已有 task 发消息
                try:
                    await _manus_post(client, "/v2/task.sendMessage", {
                        "task_id": task_id,
                        "message": {"content": user_message},
                    })
                except Exception as e:
                    # task 可能已过期/被删，重建一个
                    logger.warning(f"sendMessage 失败，重建 task: {e}")
                    data = await _manus_post(client, "/v2/task.create", {
                        "message": {"content": f"[系统指令：{SYSTEM_PROMPT}]\n\n[用户消息]\n{user_message}"},
                        "agent_profile": profile,
                        "locale": "zh-CN",
                        "hide_in_task_list": True,
                        "share_visibility": "private",
                    })
                    task_id = data["task_id"]
                    ustate["manus_task_id"] = task_id
                    save_state()
                    after_ts = int(time.time() * 1000)

            reply = await _wait_for_reply(client, task_id, after_ts)
            return reply
    except TimeoutError:
        return "Manus 正在思考中，稍等片刻再问我一次吧（任务可能还在跑）。"
    except Exception as e:
        logger.warning(f"Manus API 调用失败 ({type(e).__name__}): {e}")
        return f"抱歉，AI 服务暂时不可用，请稍后再试。\n（{type(e).__name__}）"


# ================= 命令 =================
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
        "/model - 查看/切换 AI 档位\n"
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
        "/model - 查看/切换 AI 档位\n"
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


_PROFILES = {
    "lite": "manus-1.6-lite",   # 更快
    "std": "manus-1.6",         # 标准
    "max": "manus-1.6-max",     # 最强
}


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ustate = get_user_state(update.effective_user.id)
    args = context.args
    if not args:
        await update.message.reply_text(
            f"当前档位：`{ustate.get('profile') or DEFAULT_PROFILE}`\n\n"
            "切换：`/model lite`（更快）\n"
            "`/model std`（标准）\n"
            "`/model max`（最强）\n"
            "切换后下条消息生效（含清空对话）",
            parse_mode="Markdown",
        )
        return
    key = args[0].strip().lower()
    if key not in _PROFILES:
        await update.message.reply_text(
            "档位不对，可选：`lite` / `std` / `max`", parse_mode="Markdown"
        )
        return
    ustate["profile"] = _PROFILES[key]
    ustate["manus_task_id"] = ""  # 换档位就重建 task
    save_state()
    await update.message.reply_text(
        f"✅ 已切换到 `{_PROFILES[key]}`（对话已重置）", parse_mode="Markdown"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - START_TIME)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    ustate = get_user_state(update.effective_user.id)
    token_src = "环境变量 ✅"
    manus_ok = "已配置 ✅" if MANUS_API_KEY else "未配置 ❌"
    await update.message.reply_text(
        "🤖 Leo助手运行状态（v8.0 Manus API 版）\n\n"
        f"⏱ 已运行：{h}小时{m}分{s}秒\n"
        f"🧠 AI 档位：{ustate.get('profile') or DEFAULT_PROFILE}\n"
        f"🔑 Manus Key：{manus_ok}\n"
        f"👥 已记录用户数：{len(_state['users'])}\n"
        f"🔑 Bot Token 来源：{token_src}"
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


# ================= 消息处理 =================
async def send_long_text(update: Update, text: str):
    """按 Telegram 4096 字符限制分段发送，尽量按换行切分。"""
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
    # 先回一个"思考中"，Manus 任务可能需要十几秒
    thinking = await update.message.reply_text("🤔 思考中…")
    ai_response = await get_ai_response(user_id, user_message)
    try:
        await thinking.delete()
    except Exception:
        pass
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


# ================= 启动 =================
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
    if not MANUS_API_KEY:
        logger.error("缺少 Manus API Key（OPENAI_API_KEY 环境变量），AI 功能将不可用！")
    logger.info("Leo助手 v8.0 启动（守护模式，Manus Task API）")
    backoff = 10
    while True:
        try:
            app = build_app()
            app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
            logger.warning("run_polling 意外退出，10 秒后重启")
            time.sleep(10)
            backoff = 10
        except InvalidToken:
            logger.error(
                "Telegram Bot Token 无效！请检查 TELEGRAM_BOT_TOKEN 环境变量 / GitHub Secrets。"
                "程序退出，不再重试。"
            )
            sys.exit(2)
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
