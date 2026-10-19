"""
매일경제 반도체·섹터 뉴스 수집 — Playwright 기반.

/search/news?word=반도체&startDate=TARGET 방식으로 수집.
newsType 필터 없음 (지면기사 한정 안 함).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, date, timedelta

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError("pip install playwright && playwright install chromium")

from bs4 import BeautifulSoup
from scrape_mk import Article, clean_text
from scrape_mk_stock_playwright import parse_date_time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

# 섹터 검색 키워드 — 순서대로 시도해서 20건 채움
SECTOR_KEYWORDS = ["반도체", "HBM", "파운드리"]


def _make_sector_url(keyword: str, start_date: str) -> str:
    from urllib.parse import quote
    return (
        "https://www.mk.co.kr/search/news"
        f"?word={quote(keyword)}"
        f"&sort=asc&dateType=direct&startDate={start_date}"
        "&searchField=all"
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


def collect_sector_by_date(
    target_date: str,
    max_articles: int = 20,
    fetch_body: bool = False,
) -> list[Article]:
    """
    target_date 반도체·섹터 뉴스 수집.
    SECTOR_KEYWORDS를 순서대로 검색해 max_articles 채움.
    """
    prev_date = str(date.fromisoformat(target_date) - timedelta(days=1))
    today = date.today()
    seen_urls: set[str] = set()
    results: list[Article] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        for keyword in SECTOR_KEYWORDS:
            if len(results) >= max_articles:
                break

            url = _make_sector_url(keyword, prev_date)
            page.goto(url)
            page.wait_for_load_state("networkidle", timeout=20000)

            # 더보기 클릭하며 target_date 기사가 나올 때까지
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
            candidates = [it for it in items if it["date"] == target_date and it["url"] not in seen_urls]
            candidates.sort(key=lambda x: x["time"])

            for c in candidates:
                if len(results) >= max_articles:
                    break
                seen_urls.add(c["url"])
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
                    except Exception:
                        pass

                results.append(Article(
                    index=len(results) + 1,
                    article_id=c["article_id"],
                    category="섹터",
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


if __name__ == "__main__":
    import argparse, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="매일경제 섹터 뉴스 수집 (Playwright)")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--json", default="mk_sector_articles.json")
    args = parser.parse_args()

    articles = collect_sector_by_date(args.date, max_articles=args.max)
    output = {"date": args.date, "count": len(articles), "articles": [asdict(a) for a in articles]}
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[섹터] {args.date}: {len(articles)}건")
    for a in articles:
        print(f"  {a.title[:55]} | {a.published_at}")
    print(f"저장: {args.json}")
