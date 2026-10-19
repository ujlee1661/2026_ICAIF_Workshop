"""
매일경제 삼성전자 지면기사 수집 — Playwright 기반.

핵심 발견:
- /search/news?startDate=TARGET&sort=asc&newsType=paper 로 해당 날짜 기사를 올림차순으로 수집
- endDate 없이 startDate만 사용 (endDate 포함 시 서버가 0 반환)
- 최근 기사는 "N일 전" 상대 시간 형식 → 절대 날짜로 변환 필요

사용:
    python scrape_mk_stock_playwright.py --date 2026-06-01
    python scrape_mk_stock_playwright.py --start 2025-01-01 --end 2026-06-02 --no-body
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 미설치: pip install playwright && playwright install chromium")
    sys.exit(1)

from bs4 import BeautifulSoup
from scrape_mk import Article, clean_text

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"


# ── 날짜/시간 파싱 ────────────────────────────────────────────────────────────

def parse_date_time(text: str, today: date | None = None) -> tuple[str | None, str | None]:
    """
    다양한 mk.co.kr 시간 형식 처리:
      "2026.06.01 15:30"     → ("2026-06-01", "15:30")
      "2026-06-01 17:39:22"  → ("2026-06-01", "17:39")
      "1일 전"               → (오늘-1일, "")
      "3시간 전"             → (오늘, "")
      "30분 전"              → (오늘, "")
    """
    if not text:
        return None, None
    text = text.strip()
    ref = today or date.today()

    # 절대 시간
    m = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})\s+(\d{2}):(\d{2})", text)
    if m:
        y, mo, d_, h, mi = m.groups()
        return f"{y}-{mo}-{d_}", f"{h}:{mi}"

    # 상대 시간: N일 전
    m = re.search(r"(\d+)일 전", text)
    if m:
        delta = ref - timedelta(days=int(m.group(1)))
        return str(delta), ""

    # 상대 시간: N시간 전 / N분 전
    if "시간 전" in text or "분 전" in text:
        return str(ref), ""

    # "어제"
    if "어제" in text:
        return str(ref - timedelta(days=1)), ""

    # "오늘"
    if "오늘" in text:
        return str(ref), ""

    return None, None


# ── Playwright 수집 ──────────────────────────────────────────────────────────

def _make_url(start_date: str) -> str:
    return (
        "https://www.mk.co.kr/search/news"
        "?word=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90"
        f"&sort=asc&dateType=direct&startDate={start_date}"
        "&searchField=all&newsType=paper"
    )


def _parse_items(html: str, today: date) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for item in soup.select("#list_area li.news_node a.news_item"):
        title_node = item.select_one(".news_ttl")
        tm_node = item.select_one(".time_info")
        url = item.get("href", "")
        if url and not url.startswith("http"):
            url = "https://www.mk.co.kr" + url
        d, t = parse_date_time(tm_node.text if tm_node else "", today)
        m = re.search(r"/(\d+)/?$", url)
        items.append({
            "article_id": m.group(1) if m else None,
            "title": clean_text(title_node.get_text(" ", strip=True)) if title_node else "",
            "url": url,
            "date": d,
            "time": t or "",
        })
    return items


def collect_stock_by_date(
    target_date: str,
    max_articles: int = 20,
    fetch_body: bool = True,
) -> list[Article]:
    """
    target_date("YYYY-MM-DD") 지면기사 수집 (시간 오름차순, 최대 max_articles).
    startDate = target_date - 1일 로 설정해 target_date 기사를 첫 페이지에 포함.
    """
    prev_date = str(date.fromisoformat(target_date) - timedelta(days=1))
    url = _make_url(prev_date)
    today = date.today()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle", timeout=20000)

        # 더보기 클릭하며 target_date 기사가 나올 때까지 또는 지나칠 때까지
        for _ in range(10):
            items = _parse_items(page.content(), today)
            dates = [it["date"] for it in items if it["date"]]
            if dates and max(dates) > target_date:
                break
            btn = page.query_selector("[data-btn-more]")
            if not btn:
                break
            cur = len(page.query_selector_all("#list_area li[data-li]"))
            btn.click()
            try:
                page.wait_for_function(
                    f"document.querySelectorAll('#list_area li[data-li]').length > {cur}",
                    timeout=8000,
                )
            except Exception:
                break

        items = _parse_items(page.content(), today)

        # target_date 기사만 필터 → 시간 오름차순 → 상위 max_articles
        candidates = [it for it in items if it["date"] == target_date]
        candidates.sort(key=lambda x: x["time"])
        candidates = candidates[:max_articles]

        results = []
        for i, c in enumerate(candidates, 1):
            body = ""
            if fetch_body and c["url"]:
                try:
                    page.goto(c["url"], timeout=15000)
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                    s = BeautifulSoup(page.content(), "lxml")
                    for sel in ("div.news_cnt_detail_wrap", "#article_body", ".article_body"):
                        node = s.select_one(sel)
                        if node:
                            body = clean_text(node.get_text("\n", strip=True))
                            break
                    if not body:
                        meta = s.select_one('meta[property="og:description"]')
                        if meta and meta.get("content"):
                            body = clean_text(meta["content"])
                except Exception:
                    pass

            results.append(Article(
                index=i,
                article_id=c["article_id"],
                category="종목",
                title=c["title"],
                url=c["url"],
                listed_at=f"{c['date']} {c['time']}",
                published_at=f"{c['date']} {c['time']}",
                published_date=c["date"],
                published_time=c["time"],
                body=body,
            ))

        browser.close()
        return results


def collect_stock_bulk(
    start_date: str,
    end_date: str,
    fetch_body: bool = False,
) -> list[dict]:
    """
    start_date ~ end_date 범위의 모든 지면기사 수집 (본문 기본 off).
    한 번에 최대한 많이 더보기를 클릭해 전체 수집 후 날짜 필터.
    """
    prev = str(date.fromisoformat(start_date) - timedelta(days=1))
    url = _make_url(prev)
    today = date.today()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle", timeout=20000)

        for _ in range(500):  # 최대 10,000건 (500번 × 20건)
            items = _parse_items(page.content(), today)
            dates = [it["date"] for it in items if it["date"]]
            if dates and min(d for d in dates if d) > end_date:
                # 아직 end_date 이후만 나옴 → 더 가야 함 (여기는 asc 정렬이므로 반대)
                break

            btn = page.query_selector("[data-btn-more]")
            if not btn:
                break
            cur = len(page.query_selector_all("#list_area li[data-li]"))
            btn.click()
            try:
                page.wait_for_function(
                    f"document.querySelectorAll('#list_area li[data-li]').length > {cur}",
                    timeout=10000,
                )
            except Exception:
                break

        items = _parse_items(page.content(), today)
        browser.close()

    return [
        {
            "article_id": it["article_id"],
            "title": it["title"],
            "url": it["url"],
            "date": it["date"],
            "time": it["time"],
            "category": "종목",
            "source": "mk",
            "body": "",
        }
        for it in items
        if it["date"] and start_date <= it["date"] <= end_date
    ]


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="매일경제 삼성전자 지면기사 수집 (Playwright)")
    parser.add_argument("--date", help="하루치 수집 (YYYY-MM-DD)")
    parser.add_argument("--start", help="벌크 수집 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--no-body", action="store_true")
    parser.add_argument("--json", default="mk_stock_articles.json")
    args = parser.parse_args()

    if args.date:
        articles = collect_stock_by_date(args.date, max_articles=args.max, fetch_body=not args.no_body)
        output = {"date": args.date, "count": len(articles), "articles": [asdict(a) for a in articles]}
        print(f"\n[종목] {args.date}: {len(articles)}건")
        for a in articles:
            print(f"  {a.title[:55]} | {a.published_at}")
    elif args.start:
        rows = collect_stock_bulk(args.start, args.end, fetch_body=not args.no_body)
        output = {"start": args.start, "end": args.end, "count": len(rows), "articles": rows}
        print(f"\n[종목 벌크] {args.start}~{args.end}: {len(rows)}건")
    else:
        parser.print_help()
        sys.exit(0)

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"저장: {args.json}")
