#!/usr/bin/env python3
"""LLM 抽取器：从网页纯文本里找出「真实存在的免费/试用条款」，返回原文证据句。

关键约束：模型返回的 evidence 必须能在原文中逐字找到（归一化空白后 substring 匹配），
否则丢弃——这样即使模型幻觉，也不会把编造的额度写进站点。
"""
from __future__ import annotations

import json
import re
import urllib.request

import yaml

CFG = yaml.safe_load(open("/root/.hermes/config.yaml", encoding="utf-8"))
API = CFG["providers"]["deepseek-v4"]["api"].rstrip("/")
KEY = CFG["providers"]["deepseek-v4"]["api_key"]
MODEL = "deepseek-v4-flash"

SYS = """你是"免费额度雷达"的抽取器。给你一个厂商定价页的纯文本，你要找出它对开发者**当前真实提供**的免费/试用/赠送条款。

只收这四类：
1. 永久免费档（free tier / 免费模型 / 免费额度）
2. 新用户试用额度（trial credits / 赠送金额 / 体验金）
3. 限时活动（明确写了截止日或"限时"的免费/折扣）
4. 学生/开源/创业计划（申请条件明确的免费额度）

不收：
- 付费套餐里的"包含 credits"（那是你花钱买的）
- 营销口号、导航文字、"免费注册"这类无信息量的按钮
- 已过期的活动

输出 JSON：{"offers":[{"summary":"≤50字，中文，保留关键数字与条件","evidence":"证据原句，必须逐字摘自给定文本"}]}
没有符合的就返回 {"offers":[]}。不要编造，不要改写 evidence。"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_llm(text: str, provider: str, timeout: int = 90) -> list[str]:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": f"厂商：{provider}\n\n网页文本：\n{text[:14000]}"},
        ],
        "temperature": 0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{API}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        raw = d["choices"][0]["message"]["content"] or "{}"
        data = json.loads(raw)
    except Exception:
        return []

    hay = _norm(text)
    out = []
    for item in (data.get("offers") or [])[:3]:
        ev = (item.get("evidence") or "").strip()
        sm = (item.get("summary") or "").strip()
        if not ev or _norm(ev) not in hay:
            continue  # 幻觉或改写 → 丢弃
        out.append(f"{sm}｜{ev}" if sm else ev)
    return out
