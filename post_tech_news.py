#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天自动往「外贸人家」频道推送科技 + 外贸新闻。

用法（GitHub Actions 定时触发）：
    TELEGRAM_BOT_TOKEN=xxx CHANNEL=@freenodes_daily python3 post_tech_news.py

新闻来源：公开 RSS（科技：36kr/IT之家/少数派；外贸：雨果网/亿邦动力）。
仅依赖 Python 标准库。
"""

import html
import json
import logging
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("tech-news")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "@freenodes_daily")
if not TOKEN:
    sys.exit("缺少 TELEGRAM_BOT_TOKEN")

# RSS 源：名称 -> 地址
TECH_FEEDS = [
    ("36氪快讯", "https://www.36kr.com/feed"),
    ("IT之家", "https://www.ithome.com/rss/"),
    ("少数派", "https://sspai.com/feed"),
]

# 外贸资讯源（WTO 官方，英文但最权威）
TRADE_FEEDS = [
    ("WTO", "http://www.wto.org/library/rss/latest_news_e.xml"),
]

MAX_ITEMS_PER_SECTION = 5
HTTP_TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_feed(name: str, url: str) -> list:
    """抓一个 RSS，返回 [{title, link, src}]。"""
    items = []
    try:
        data = http_get(url)
        root = ET.fromstring(data)
        for entry in root.iter("item"):  # rss2.0
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "src": name})
            if len(items) >= 4:
                break
        if not items:  # atom
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(ns + "entry"):
                t = entry.find(ns + "title")
                l = entry.find(ns + "link")
                title = (t.text if t is not None and t.text else "").strip()
                link = l.get("href", "") if l is not None else ""
                if title and link:
                    items.append({"title": title, "link": link, "src": name})
                if len(items) >= 4:
                    break
    except Exception as e:
        logger.warning("RSS 抓取失败 %s (%s): %s", name, url, e)
    return items


def build_message(tech_items: list, trade_items: list, tip: str) -> str:
    date_str = time.strftime("%m月%d日", time.localtime())
    lines = ["📰 <b>每日资讯 · %s</b>" % date_str, ""]
    if tech_items:
        lines.append("🔬 <b>科技</b>")
        for i, it in enumerate(tech_items[:MAX_ITEMS_PER_SECTION], 1):
            title = html.escape(it["title"][:60])
            src = html.escape(it["src"])
            lines.append('%d. <a href="%s">%s</a> <i>(%s)</i>' % (i, it["link"], title, src))
        lines.append("")
    if trade_items:
        lines.append("🌍 <b>外贸</b>")
        for i, it in enumerate(trade_items[:MAX_ITEMS_PER_SECTION], 1):
            title = html.escape(it["title"][:60])
            src = html.escape(it["src"])
            lines.append('%d. <a href="%s">%s</a> <i>(%s)</i>' % (i, it["link"], title, src))
        lines.append("")
    if tip:
        lines.append("💡 <b>今日干货</b>")
        lines.append(tip)
        lines.append("")
    lines.append("—— 外贸人家 · 每日更新")
    return "\n".join(lines)


# 每日轮换的外贸干货（SOHO / FB投流 / INS / TK获客）
DAILY_TIPS = [
    "🏠 <b>SOHO做外贸起步</b>：先定1-2个主打产品深耕，别贪多。注册香港公司+离岸账户收款，用WhatsApp Business养号，前3个月每天加10个精准客户，坚持比技巧重要。",
    "📣 <b>FB投流入门</b>：新户先跑互动广告养像素7天，日预算$5起测素材。CTR低于1%直接换素材，别死磕。受众先宽后窄，转化稳定后再叠加兴趣词。",
    "📸 <b>INS获客</b>：主页Bio写清你是做什么+WhatsApp直达链接。每天1条Reels展示产品使用场景，标签混用大标签+精准长尾标签，主动评论同行粉丝是最快的冷启动。",
    "🎵 <b>TK获客</b>：TikTok Shop+短视频双管齐下。前3秒必须出产品卖点，挂小黄车转化。直播每天固定时段开，哪怕只有几个人也要坚持，算法给坚持的人流量。",
    "💰 <b>SOHO收款</b>：小额用PayPal/Wise，大额走离岸公司TT。警惕尼日利亚等高风险地区订单，首单务必全款或至少50%定金发货。",
    "🔍 <b>找客户渠道</b>：海关数据+Google Maps+LinkedIn组合拳。海关数据找进口商，Google Maps按区域扫街式开发，LinkedIn加采购负责人，三管齐下不愁没客户。",
    "✉️ <b>开发信技巧</b>：标题别写Dear Sir，要写具体产品+利益点如'Reduce your sourcing cost 15% - LED strips'。正文3段以内，附件只放1页PDF，第一封不报价只求回复。",
]


def pick_tip() -> str:
    # 按日期轮换，保证每天一条不重样
    idx = int(time.strftime("%j", time.localtime())) % len(DAILY_TIPS)
    return DAILY_TIPS[idx]


def send_to_channel(text: str):
    url = "https://api.telegram.org/bot%s/sendMessage" % TOKEN
    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA["User-Agent"]},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError("Telegram API 返回失败: %s" % data)
    logger.info("已推送到 %s", CHANNEL)


def main():
    tech_items = []
    for name, url in TECH_FEEDS:
        tech_items.extend(fetch_feed(name, url))
    trade_items = []
    for name, url in TRADE_FEEDS:
        trade_items.extend(fetch_feed(name, url))
    if not tech_items and not trade_items:
        logger.error("所有 RSS 源都抓取失败，今天不推送")
        sys.exit(1)
    msg = build_message(tech_items, trade_items, pick_tip())
    logger.info("科技 %d 条，外贸 %d 条+干货，准备推送",
                len(tech_items), len(trade_items))
    send_to_channel(msg)


if __name__ == "__main__":
    main()
