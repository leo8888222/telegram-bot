#!/usr/bin/env python3
"""
个人 TG 自动回复 userbot
监听个人账号的私聊消息，用 Manus AI 自动回复
"""
import os
import sys
import asyncio
import logging
import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("userbot")

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
MANUS_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MANUS_BASE = os.environ.get("OPENAI_API_BASE", "https://api.manus.ai").rstrip("/")
MODEL = "manus-1.6-lite"

if not all([API_ID, API_HASH, SESSION]):
    log.error("缺少 TG_API_ID / TG_API_HASH / TG_SESSION，退出")
    sys.exit(1)
if not MANUS_API_KEY:
    log.error("缺少 OPENAI_API_KEY（Manus Key），退出")
    sys.exit(1)

tasks = {}

SYSTEM_PROMPT = """你是一个聪明、自然的聊天伙伴。有人在 Telegram 上私聊，你就像朋友平时聊天那样回复。
说话风格：简洁、聪明、带点幽默感，用中文。不要啰嗦。
重要规则：
1. 绝对不要说你是 AI、助手、机器人或自动回复，就像真人一样聊天。
2. 不要编造重要承诺、行程或决定，遇到拿不准的重要事项，就自然地说"这个我晚点确认下再回你"。
3. 不要提 Manus、API 等技术细节。
4. 像真人一样对话，可以反问、接梗，保持对话流畅。
"""

async def manus_reply(user_id: int, text: str) -> str:
    headers = {"API_KEY": MANUS_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as cli:
        task_id = tasks.get(user_id)
        if not task_id:
            r = await cli.post(f"{MANUS_BASE}/v2/task.create", headers=headers, json={
                "prompt": SYSTEM_PROMPT,
                "agentProfile": MODEL,
            })
            r.raise_for_status()
            task_id = r.json()["task_id"]
            tasks[user_id] = task_id
            log.info(f"为用户 {user_id} 创建 Manus task {task_id}")
        r = await cli.post(f"{MANUS_BASE}/v2/task.sendMessage", headers=headers, json={
            "task_id": task_id,
            "content": text,
        })
        r.raise_for_status()
        last_id = None
        for _ in range(40):
            await asyncio.sleep(3)
            r = await cli.post(f"{MANUS_BASE}/v2/task.listMessages", headers=headers, json={
                "task_id": task_id,
                "last_message_id": last_id,
            })
            r.raise_for_status()
            msgs = r.json().get("messages", [])
            for m in msgs:
                last_id = m.get("message_id", last_id)
                if m.get("role") == "assistant" and m.get("content"):
                    return m["content"]
        return "嗯…让我想想，晚点回你"

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
                reply = await manus_reply(uid, text)
            except Exception as e:
                log.error(f"Manus 调用失败：{e}")
                reply = "在忙，晚点回你"
        await event.reply(reply)
        log.info(f"已回复 {name}({uid})")

    log.info("开始监听私聊消息…")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
