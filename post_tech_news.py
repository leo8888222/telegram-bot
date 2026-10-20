#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天自动往「外贸人家」频道推送科技 + 政策 + 外贸新闻。

用法（GitHub Actions 定时触发）：
    TELEGRAM_BOT_TOKEN=xxx CHANNEL=@freenodes_daily python3 post_tech_news.py

新闻来源：公开 RSS（科技：36kr/IT之家/少数派；政策：中新网要闻按外贸关键词过滤；
外贸：WTO 官方）。
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

# 政策源：中新网要闻导读（综合新闻，按外贸/政策关键词过滤出相关条目）
POLICY_FEEDS = [
    ("中新网", "https://www.chinanews.com.cn/rss/importnews.xml"),
]
POLICY_KEYWORDS = [
    "外贸", "出口", "进口", "贸易", "关税", "跨境", "海关", "商务部",
    "退税", "RCEP", "广交会", "汇率", "外资", "自贸", "一带一路",
]

# 外贸资讯源（WTO 官方，英文但最权威）
TRADE_FEEDS = [
    ("WTO", "http://www.wto.org/library/rss/latest_news_e.xml"),
]

MAX_ITEMS_PER_SECTION = 5
MAX_POLICY_ITEMS = 4
HTTP_TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_feed(name: str, url: str, limit: int = 4) -> list:
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
            if len(items) >= limit:
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
                if len(items) >= limit:
                    break
    except Exception as e:
        logger.warning("RSS 抓取失败 %s (%s): %s", name, url, e)
    return items


def fetch_policy_items() -> list:
    """抓政策源，按关键词过滤出外贸相关条目。"""
    picked = []
    seen = set()
    for name, url in POLICY_FEEDS:
        # 政策源多抓一些再过滤
        for it in fetch_feed(name, url, limit=30):
            if it["title"] in seen:
                continue
            if any(k in it["title"] for k in POLICY_KEYWORDS):
                picked.append(it)
                seen.add(it["title"])
            if len(picked) >= MAX_POLICY_ITEMS:
                break
        if len(picked) >= MAX_POLICY_ITEMS:
            break
    return picked


# ---- 去重：已发过的链接记在 sent_links.json 里，下次自动跳过 ----
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent_links.json")
HISTORY_KEEP = 300  # 只保留最近 300 条，防文件无限变大


def load_sent_links() -> set:
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
    except Exception:
        pass
    return set()


def drop_sent(items: list, sent: set) -> list:
    """过滤掉已经发过的条目（按链接判断）。"""
    return [it for it in items if it["link"] not in sent]


def save_sent_links(sent: set):
    links = list(sent)[-HISTORY_KEEP:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False)
        logger.info("已发记录更新：共 %d 条", len(links))
    except Exception as e:
        logger.warning("保存已发记录失败: %s", e)


def build_message(tech_items: list, policy_items: list, trade_items: list, tip: str) -> str:
    date_str = time.strftime("%m月%d日", time.localtime())
    lines = ["📰 <b>每日资讯 · %s</b>" % date_str, ""]
    if tech_items:
        lines.append("🔬 <b>科技</b>")
        for i, it in enumerate(tech_items[:MAX_ITEMS_PER_SECTION], 1):
            title = html.escape(it["title"][:60])
            src = html.escape(it["src"])
            lines.append('%d. <a href="%s">%s</a> <i>(%s)</i>' % (i, it["link"], title, src))
        lines.append("")
    if policy_items:
        lines.append("📜 <b>政策</b>")
        for i, it in enumerate(policy_items[:MAX_POLICY_ITEMS], 1):
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


# 每日轮换的外贸干货（新手起步 / FB投流 / TK运营 / INS / 收款 / 找客户 / 开发信）
DAILY_TIPS = [
    "🌱 <b>新手起步① · 先选对赛道</b>：新手别一上来铺十几个产品。先选1-2个类目深耕，优先选体积小、单价$10-50、复购或耗材类的产品，物流便宜、试错成本低。去亚马逊Best Sellers和TK热榜看什么在卖，先模仿再超越。",
    "🌱 <b>新手起步② · 资质和收款先备好</b>：个体户/公司营业执照+进出口经营权（现在备案制，很快），没单时可先挂靠外贸公司出货。收款提前开好：企业账户、PayPal、Wise、连连/PingPong，客户问付款方式时秒回，专业度拉满。",
    "🌱 <b>新手起步③ · 第一个客户从哪来</b>：零基础起步三件套：①阿里国际站/MIC开免费会员先练手；②Google搜产品词+importer/wholesaler，每天发10封开发信；③FB/INS/TK同步发产品内容。坚持90天，第一单大概率就来了。",
    "📣 <b>FB投流① · 开户与养号</b>：新BM先用主页发一周自然内容，再绑卡跑互动广告养像素（Page Post Engagement，日预算$5-10）。像素装到独立站并测试事件，没数据的像素等于没投。账号被封多半是素材违规和频繁改设置，前两周动作要慢。",
    "📣 <b>FB投流② · 测品方法</b>：一套测品公式：1个广告系列→3个受众组（宽泛/兴趣/类目词）→每组2-3个素材，日预算$5/组跑2天。CTR＜1%杀素材，CPC贵过类目均值杀受众，有加购没下单就查落地页价格和运费。留下赢家再放大。",
    "📣 <b>FB投流③ · 放量与再营销</b>：出单稳定的素材别直接拉大预算，每天+20%稳步放量，或复制到新系列翻预算。再营销必做：网站访客、加购未购、视频看过75%的人单独建组，低预算高ROI，老客池是你最稳的订单来源。",
    "🎵 <b>TK运营① · 起号与选品</b>：新号前5条视频定人群，垂直发同一类产品场景，别东一条西一条。选品看三点：演示性强（3秒看懂用法）、痛点明显、TikTok Shop同类销量在涨。搬运必死，原创实拍哪怕粗糙，流量也比搬运高。",
    "🎵 <b>TK运营② · 带货与直播</b>：视频前3秒必须给结果或冲突（脏污对比、开箱瞬间），中段讲用法，结尾挂小黄车。直播固定时段、固定话术循环讲1个爆品，新人直播间先靠短视频引流进人，再谈转化，别坐等自然流量。",
    "📸 <b>INS获客</b>：主页Bio写清你是做什么+WhatsApp直达链接。每天1条Reels展示产品使用场景，标签混用大标签+精准长尾标签，主动评论同行粉丝是最快的冷启动。客户询盘尽量1小时内回，INS买家同时在问3-5家，谁快谁赢。",
    "💰 <b>SOHO收款</b>：小额用PayPal/Wise，大额走公司账户TT。警惕高风险地区订单，首单务必全款或至少30-50%定金再备货。报价时把收款手续费算进成本，别订单接了利润没了。",
    "🔍 <b>找客户渠道</b>：海关数据+Google Maps+LinkedIn组合拳。海关数据找真实进口商，Google Maps按城市扫同类经销商，LinkedIn加采购负责人。再配上Google指令 site: 搜索，每天稳定开发20个精准客户。",
    "✉️ <b>开发信技巧</b>：标题别写Dear Sir，要写具体产品+利益点，如'Reduce your sourcing cost 15% - LED strips'。正文3段以内，附件只放1页PDF，第一封不报价只求回复。没回的别放弃，第3天、7天各跟一封，回复率能翻倍。",
    "🚢 <b>报价基础课</b>：报价前先分清FOB（离岸价，不含海运）和CIF（到港价，含海运保险）。新手建议先报EXW/FOB练手，运费让货代实时核价再报，别拍脑袋包邮到港，一柜运费波动能吃掉全部利润。",
    "🧾 <b>退税常识</b>：有进出口权的公司出口可享退税，不同产品退税率不同（可到税务总局查HS编码对应退税率），这笔钱常常就是你的纯利润。单证（报关单、发票、提单）留全，退税申报别逾期。",
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
    sent = load_sent_links()
    tech_items = []
    for name, url in TECH_FEEDS:
        tech_items.extend(fetch_feed(name, url))
    policy_items = fetch_policy_items()
    trade_items = []
    for name, url in TRADE_FEEDS:
        trade_items.extend(fetch_feed(name, url))
    # 去重：发过的全部跳过
    tech_new = drop_sent(tech_items, sent)
    policy_new = drop_sent(policy_items, sent)
    trade_new = drop_sent(trade_items, sent)
    logger.info("去重：科技 %d→%d，政策 %d→%d，外贸 %d→%d",
                len(tech_items), len(tech_new),
                len(policy_items), len(policy_new),
                len(trade_items), len(trade_new))
    if not tech_new and not policy_new and not trade_new:
        logger.info("今天没有新资讯（全是发过的），跳过推送")
        return
    msg = build_message(tech_new, policy_new, trade_new, pick_tip())
    send_to_channel(msg)
    # 发送成功才记入已发列表
    for it in tech_new + policy_new + trade_new:
        sent.add(it["link"])
    save_sent_links(sent)


if __name__ == "__main__":
    main()
