#!/usr/bin/env python3
"""
个人 TG 自动回复 userbot
监听个人账号的私聊消息，用 Manus AI 自动回复
"""
import os
import sys
import asyncio
import logging
import time
import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("userbot")

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
MANUS_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MANUS_BASE = "https://api.manus.ai"
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

def _headers():
    return {"API_KEY": MANUS_API_KEY, "Content-Type": "application/json"}

async def _manus_post(client, path, payload):
    r = await client.post(f"{MANUS_BASE}{path}", headers=_headers(), json=payload)
    r.raise_for_status()
    return r.json()

async def _manus_get(client, path, params):
    r = await client.get(f"{MANUS_BASE}{path}", headers=_headers(), params=params)
    r.raise_for_status()
    return r.json()

def _extract_reply(messages, after_ts):
    for m in messages:
        if m.get("type") != "assistant_message":
            continue
        try:
            ts = int(m.get("timestamp", 0))
        except (ValueError, TypeError):
            ts = 0
        if ts <= after_ts:
            continue
        content = m.get("content") or ""
        if isinstance(content, dict):
            content = content.get("text") or str(content)
        if content.strip():
            return content.strip(), ts
    return None, after_ts

async def manus_reply(user_id: int, text: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        task_id = tasks.get(user_id)
        now_ts = int(time.time() * 1000)
        if not task_id:
            first_content = f"[系统指令：{SYSTEM_PROMPT}]\n\n[用户消息]\n{text}"
            data = await _manus_post(client, "/v2/task.create", {
                "message": {"content": first_content},
                "agent_profile": MODEL,
                "locale": "zh-CN",
                "hide_in_task_list": True,
                "share_visibility": "private",
            })
            task_id = data["task_id"]
            tasks[user_id] = task_id
            log.info(f"为用户 {user_id} 创建 Manus task: {task_id}")
            after_ts = now_ts
        else:
            await _manus_post(client, "/v2/task.sendMessage", {
                "task_id": task_id,
                "message": {"content": text},
            })
            after_ts = now_ts

        # 轮询回复
        for _ in range(40):
            await asyncio.sleep(3)
            try:
                data = await _manus_get(client, "/v2/task.listMessages",
                    {"task_id": task_id, "order": "desc", "limit": 10})
                reply, after_ts = _extract_reply(data.get("messages", []), after_ts)
                if reply:
                    return reply
            except Exception as e:
                log.warning(f"轮询 Manus 消息失败: {e}")
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
