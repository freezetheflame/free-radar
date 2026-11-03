#!/usr/bin/env python3
"""免费额度雷达：抓官方定价/试用页，抽取"免费/trial/credit"句子，做变更检测，生成静态站数据。

设计取舍：不猜数字、不编额度。每条 offer 只保留**官方页面原文片段** + 链接 + 最近核验时间，
用户点进去看准确条款。这样站点不会因为模型/额度调整而过期撒谎。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml
from extract_llm import extract_llm

ROOT = Path(__file__).resolve().parent
DB = ROOT / "radar.db"
SITE = ROOT / "docs"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

KEYWORDS = [
    "免费", "试用", "额度", "赠送", "白嫖", "限时", "学生", "补贴",
    "free", "trial", "credit", "credits", "no cost", "starter", "student",
]
BAD = ["登录", "注册页面", "cookie", "javascript", "隐私政策", "服务条款"]


def fetch(url: str, timeout: int = 25) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get_content_charset() or "utf-8"
        return raw.decode(enc, "ignore"), r.status


def fetch_reader(url: str, timeout: int = 45) -> tuple[str, int]:
    """JS 重页面的兜底：走 r.jina.ai 的只读渲染，返回 markdown 文本。"""
    req = urllib.request.Request("https://r.jina.ai/" + url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore"), r.status


def text_lines(doc: str) -> list[str]:
    doc = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?is)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", doc)
    text = re.sub(r"(?s)<[^>]+>", " ", doc)
    text = html.unescape(text)
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if 8 <= len(line) <= 240:
            out.append(line)
    return out


CTA_ONLY = re.compile(r"(?i)^(download|get started|start|sign up|try|claim|learn more|contact|book a demo)[^0-9$]{0,40}$")
QUANT = re.compile(r"(\$\s?\d|\d+\s*(?:元|美元|万|token|tokens|requests|req|rpm|tpm|天|day|month|mo|hours|小时|credit|credits))", re.I)


def score(line: str) -> int:
    low = line.lower()
    if any(b in low for b in BAD):
        return -1
    if CTA_ONLY.match(line.strip()):
        return -1
    strong = any(k in low for k in ("free tier", "free of charge", "免费", "trial", "试用", "credits", "额度", "赠送"))
    if not strong:
        return -1
    s = 3 if any(k in low for k in ("free tier", "free of charge", "免费", "trial", "试用")) else 1
    s += 2 if QUANT.search(line) else 0
    if len(line) < 12:
        return -1
    return s if s >= 3 else -1


NAVISH = ("产品动态", "产品定价", "配置报价器", "云上成本", "联系我们", "登录", "注册页面", "文档中心", "查看详情", "了解更多")

FREE_WORDS = ("免费", "free", "trial", "试用", "额度", "赠送", "credit", "credits", "白嫖")
PAID_ONLY = re.compile(r"^\s*\$\s?\d+(\.\d+)?\s*/\s*mo", re.I)


def valid_snippet(s: str) -> bool:
    low = s.lower()
    if len(s) < 20:
        return False
    if any(n in s for n in NAVISH):
        return False
    # 英文用词边界，避免 industrial 里的 trial、career 里的 free 之类误命中
    pats = [r"\bfree\b", r"\btrial\b", r"\bcredits?\b", r"免费", r"试用", r"额度", r"赠送"]
    hits = [m.start() for p in pats for m in re.finditer(p, low)]
    if not hits or min(hits) > 50:
        return False
    # 导航式菜单：没有数字、没有句读、还反复出现"免费"
    if not re.search(r"\d", s) and low.count("免费") >= 2:
        return False
    if PAID_ONLY.match(s) and not re.search(r"\b(free|trial)\b|免费", low):
        return False
    if "注册" in s and not re.search(r"\d", s):
        return False
    return True




def extract(doc: str, limit: int = 3) -> list[str]:
    lines = text_lines(doc)
    scored = []
    for line in lines:
        sc = score(line)
        if sc >= 3:
            scored.append((sc, line))
    picked = _pick(scored, limit)
    if picked:
        return picked
    # 兜底：放宽到「免费/trial/credit 且带数字」，但排除导航行与纯 CTA
    loose = []
    for line in lines:
        low = line.lower()
        if any(n in line for n in NAVISH) or any(b in low for b in BAD):
            continue
        if CTA_ONLY.match(line.strip()):
            continue
        if any(k in low for k in ("free", "免费", "trial", "试用", "credit")) and QUANT.search(line):
            loose.append((2, line))
    return _pick(loose, 2)


def _pick(scored: list[tuple[int, str]], limit: int) -> list[str]:
    seen, picked = set(), []
    for sc, line in sorted(scored, key=lambda x: -x[0]):
        key = re.sub(r"\d+", "#", line.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        picked.append(line)
        if len(picked) >= limit:
            break
    return picked


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS offers(
        sid TEXT, url TEXT, snippet TEXT, hash TEXT, first_seen TEXT, last_seen TEXT,
        status TEXT, fail_count INTEGER DEFAULT 0, PRIMARY KEY(sid, hash))""")
    con.execute("""CREATE TABLE IF NOT EXISTS sources(
        sid TEXT PRIMARY KEY, name TEXT, type TEXT, region TEXT, url TEXT,
        last_ok TEXT, last_error TEXT, fail_count INTEGER DEFAULT 0)""")
    return con


def main() -> int:
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    con = db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = fail = 0

    sources = [] if os.environ.get("EXPORT_ONLY") == "1" else cfg["sources"]
    for src in sources:
        sid, url = src["id"], src["url"]
        try:
            doc, code = fetch(url)
            snippets = extract(doc)
            if not snippets:
                doc, code = fetch_reader(url)
                snippets = extract(doc)
            # LLM 抽取优先：证据句必须能在原文里逐字找到
            plain = "\n".join(text_lines(doc))
            if plain.strip():
                llm_snips = extract_llm(plain, src["name"])
                if llm_snips:
                    snippets = llm_snips
            if not snippets:
                raise ValueError("no candidate lines")
            ok += 1
            con.execute(
                "INSERT INTO sources(sid,name,type,region,url,last_ok,last_error,fail_count) "
                "VALUES(?,?,?,?,?,?,NULL,0) ON CONFLICT(sid) DO UPDATE SET "
                "name=excluded.name,type=excluded.type,region=excluded.region,url=excluded.url,"
                "last_ok=excluded.last_ok,last_error=NULL,fail_count=0",
                (sid, src["name"], src["type"], src["region"], url, now))
            for sn in snippets:
                h = hashlib.sha1(sn.encode("utf-8")).hexdigest()[:16]
                con.execute(
                    "INSERT INTO offers(sid,url,snippet,hash,first_seen,last_seen,status) "
                    "VALUES(?,?,?,?,?,?,'live') ON CONFLICT(sid,hash) DO UPDATE SET last_seen=excluded.last_seen,status='live'",
                    (sid, url, sn, h, now, now))
            print(f"OK   {sid:18s} {len(snippets)} snippets")
        except Exception as e:  # noqa: BLE001
            fail += 1
            con.execute(
                "INSERT INTO sources(sid,name,type,region,url,last_ok,last_error,fail_count) "
                "VALUES(?,?,?,?,?,NULL,?,1) ON CONFLICT(sid) DO UPDATE SET "
                "last_error=excluded.last_error, fail_count=sources.fail_count+1",
                (sid, src["name"], src["type"], src["region"], url, f"{type(e).__name__}: {e}"[:200]))
            print(f"FAIL {sid:18s} {type(e).__name__}: {str(e)[:80]}")
        time.sleep(0.6)

    # 超过 14 天没再出现的片段标记 stale
    con.execute("UPDATE offers SET status='stale' WHERE status='live' AND last_seen < date('now','-14 day')")
    con.commit()

    ok = con.execute("SELECT COUNT(*) FROM sources WHERE last_ok IS NOT NULL").fetchone()[0]
    fail = con.execute("SELECT COUNT(*) FROM sources WHERE last_error IS NOT NULL AND last_ok IS NULL").fetchone()[0]
    rows = con.execute("SELECT sid,url,snippet,first_seen,last_seen,status FROM offers WHERE status='live'").fetchall()
    meta = {r[0]: r for r in con.execute("SELECT sid,name,type,region,last_ok,last_error,fail_count FROM sources")}

    offers = []
    for sid, url, sn, first_seen, last_seen, status in rows:
        if not valid_snippet(sn):
            continue
        m = meta.get(sid)
        offers.append({
            "sid": sid, "provider": m[1] if m else sid, "type": m[2] if m else "api",
            "region": m[3] if m else "global", "url": url, "text": sn.strip().strip("|").strip(),
            "first_seen": first_seen, "last_seen": last_seen, "status": status,
            "is_new": (now[:10] == first_seen[:10]),
            "source_error": (m[5] if m else None),
        })
    offers.sort(key=lambda o: (o["type"], o["provider"]))
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps({
        "generated_at": now, "ok": ok, "fail": fail, "offers": offers,
        "sources": [{"sid": k, "name": v[1], "type": v[2], "region": v[3], "last_ok": v[4], "last_error": v[5], "fail_count": v[6]} for k, v in meta.items()],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{ok} ok / {fail} fail → {len(offers)} offers → docs/data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
