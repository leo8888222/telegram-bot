#!/usr/bin/env python3
"""
个人 TG 自动回复 userbot
监听个人账号的私聊消息，用 Groq AI 快速回复（秒级）
"""
import os
import sys
import asyncio
import logging
import time
import httpx
from collections import defaultdict, deque
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("userbot")

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"
MODEL = "qwen/qwen3.8-27b"

if not all([API_ID, API_HASH, SESSION]):
    log.error("缺少 TG_API_ID / TG_API_HASH / TG_SESSION，退出")
    sys.exit(1)
if not GROQ_API_KEY:
    log.error("缺少 GROQ_API_KEY，退出")
    sys.exit(1)

# 每个用户保留最近 10 轮对话（20 条消息）用于上下文
histories = defaultdict(lambda: deque(maxlen=20))
# 记录连续失败次数，用于兜底频率控制
fail_counts = defaultdict(int)
last_fail_reply = defaultdict(float)

SYSTEM_PROMPT = """你是一个聪明、自然的聊天伙伴。有人在 Telegram 上私聊你，你就像朋友平时聊天那样回复。
说话风格：简洁、聪明、带点幽默感，用中文。不要啰嗦，回复控制在 1-3 句话。
重要规则：
1. 绝对不要说你是 AI、助手、机器人或自动回复，就像真人一样聊天。
2. 不要编造重要承诺、行程或决定。遇到拿不准的重要事项，就自然地说"这个我晚点确认下再回你"。
3. 不要提任何技术细节（API、模型、Manus、Groq 等）。
4. 像真人一样对话：可以反问、接梗、延续话题，保持对话流畅自然。
5. 不要加任何"自动回复"之类的小尾巴。
"""

# 兜底回复池，避免每次都回同一句
FALLBACK_REPLIES = [
    "哈哈，刚在忙，看到啦",
    "嗯嗯，我看下再回你",
    "在呢在呢，刚没看手机",
    "收到，稍等我一下",
]

async def groq_reply(user_id: int, text: str) -> str:
    """调用 Groq Chat Completions，带上下文，秒级返回"""
    hist = histories[user_id]
    hist.append({"role": "user", "content": text})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(hist)

    start = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{GROQ_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 500,
            },
        )
        r.raise_for_status()
        data = r.json()

    elapsed = time.time() - start
    reply = data["choices"][0]["message"]["content"].strip()
    hist.append({"role": "assistant", "content": reply})
    log.info(f"Groq 回复用户 {user_id} 耗时 {elapsed:.1f}s")
    # 成功后重置失败计数
    fail_counts[user_id] = 0
    return reply

def fallback_reply(user_id: int) -> str:
    """API 失败时的兜底：轮换回复，避免重复"""
    fail_counts[user_id] += 1
    idx = (fail_counts[user_id] - 1) % len(FALLBACK_REPLIES)
    # 如果 5 分钟内已经用过兜底，就不再回复，避免刷屏
    now = time.time()
    if now - last_fail_reply[user_id] < 300:
        return None
    last_fail_reply[user_id] = now
    return FALLBACK_REPLIES[idx]

async def main():
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    log.info(f"Userbot 已上线：@{me.username or me.id}（{me.first_name}）")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        if not event.is_private:
            return
        sender = await event.get_sender()
        if sender.is_self or sender.bot:
            return
        uid = sender.id
        name = getattr(sender, "first_name", str(uid))
        text = event.message.message or ""
        if not text.strip():
            return
        log.info(f"收到 {name}({uid}) 的私聊：{text[:50]}")
        async with client.action(event.chat_id, "typing"):
            try:
                reply = await groq_reply(uid, text)
            except Exception as e:
                log.error(f"Groq 调用失败（用户 {uid}）：{type(e).__name__}: {e}")
                reply = fallback_reply(uid)
                if reply is None:
                    log.info(f"用户 {uid} 兜底冷却中，跳过回复")
                    return
        await event.reply(reply)
        log.info(f"已回复 {name}({uid})")

    log.info("开始监听私聊消息…")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
