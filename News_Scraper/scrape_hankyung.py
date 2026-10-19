from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scrape_mk import Article, clean_text, get_soup, parse_input_time

PAGE_DELAY = 0.4   # 페이지 요청 간 딜레이(초) — rate limiting 방지

# 섹션별 설정: (URL, 수집 시작 페이지 추정용 날짜-페이지 기준점)
# 기준점: (날짜, 페이지) — 해당 날짜의 기사가 약 이 페이지 근처에 있음
# 2025-06-02 측정값 기준. 날짜가 오래될수록 더 높은 페이지 번호.
SECTION_CONFIGS = [
    {
        "url": "https://www.hankyung.com/economy/macro",
        "name": "macro",
        # page 1=2026-06-02, page 60=2025-01-16, page 65≈2025-01-01, page 75=데이터없음
        "page_anchors": [(1, "2026-06-02"), (60, "2025-01-16"), (65, "2025-01-01")],
        "max_page": 72,
    },
    {
        "url": "https://www.hankyung.com/economy/economic-policy",
        "name": "economic-policy",
        # page 1=2026-06-02, page 60=2025-11-30, page 100=2025-07-22,
        # page 131=2025-03-24, page ~151=2025-01-01 (4일/page)
        "page_anchors": [(1, "2026-06-02"), (60, "2025-11-30"), (100, "2025-07-22"),
                         (131, "2025-03-24"), (151, "2025-01-01")],
        "max_page": 160,
    },
]
SECTION_URLS = [c["url"] for c in SECTION_CONFIGS]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko",
}


@dataclass
class HankyungItem:
    index: int
    article_id: str | None
    title: str
    url: str
    listed_at: str | None
    section: str


def extract_hankyung_body(soup: BeautifulSoup) -> str:
    """한경 기사 본문 추출. 광고·스크립트 제거 후 텍스트 반환."""
    body_node = soup.select_one("div.article-body#articletxt")
    if not body_node:
        body_node = soup.select_one("div.article-body")
    if not body_node:
        meta = soup.select_one('meta[property="og:description"]')
        return clean_text(meta["content"]) if meta and meta.get("content") else ""

    # 광고 영역 제거
    for ad in body_node.select("div.ad-area-wrap, script, .ad-wrap"):
        ad.decompose()

    paragraphs = []
    for elem in body_node.find_all(["p", "br"], recursive=True):
        text = clean_text(elem.get_text(" ", strip=True))
        if text and len(text) > 10:
            paragraphs.append(text)

    if paragraphs:
        return "\n".join(paragraphs)

    return clean_text(body_node.get_text("\n", strip=True))


def fetch_hankyung_page(
    session: requests.Session,
    section_url: str,
    page: int = 1,
) -> list[HankyungItem]:
    """한경 섹션 목록 한 페이지 파싱 → HankyungItem 리스트 반환."""
    params = {"page": page} if page > 1 else {}
    section_name = section_url.split("/")[-1]

    try:
        soup = get_soup(session, section_url, params=params)
        time.sleep(PAGE_DELAY)
    except Exception:
        return []

    items: list[HankyungItem] = []
    for index, cont in enumerate(soup.select("div.text-cont"), start=1 + (page - 1) * 20):
        link_tag = cont.select_one("h2.news-tit a") or cont.select_one("a[href]")
        if not link_tag:
            continue

        url = link_tag.get("href", "")
        if not url.startswith("http"):
            url = urljoin(section_url, url)
        if not url.startswith("http"):
            continue

        title = clean_text(link_tag.get_text(" ", strip=True))
        date_node = cont.select_one("p.txt-date")
        listed_at = clean_text(date_node.get_text(" ", strip=True)) if date_node else None

        # article_id: URL 끝 alphanumeric
        m = re.search(r"/article/([A-Za-z0-9]+)$", url)
        article_id = m.group(1) if m else None

        items.append(HankyungItem(
            index=index,
            article_id=article_id,
            title=title,
            url=url,
            listed_at=listed_at,
            section=section_name,
        ))
    return items


def collect_economy_bulk(
    start_date: str,
    end_date: str,
    max_pages: int = 80,
) -> dict[str, list[dict]]:
    """
    start_date ~ end_date 범위의 경제 기사를 한 번에 수집해 {date: [article...]} 반환.
    collect_all.py 에서 전체 기간 수집 시 매 날짜마다 page 1부터 재시작하는 비효율 방지.
    """
    result: dict[str, list[dict]] = {}

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for section_url in SECTION_URLS:
            for page in range(1, max_pages + 1):
                items = fetch_hankyung_page(session, section_url, page=page)
                if not items:
                    break

                done = False
                for item in items:
                    date, time_ = parse_input_time(item.listed_at)
                    if date is None:
                        continue
                    if date > end_date:
                        continue
                    if date < start_date:
                        done = True
                        break
                    try:
                        soup = get_soup(session, item.url)
                        body = extract_hankyung_body(soup)
                    except Exception:
                        body = ""
                    result.setdefault(date, []).append({
                        "article_id": item.article_id,
                        "title": item.title,
                        "url": item.url,
                        "date": date,
                        "time": time_ or "",
                        "category": "경제",
                        "source": "hankyung",
                        "body": body,
                    })
                if done:
                    break
    return result


def collect_economy_by_date(
    target_date: str,
    max_articles: int = 20,
) -> list[Article]:
    """
    target_date("YYYY-MM-DD")에 해당하는 경제 기사 수집.
    거시경제 + 경제정책 두 섹션을 합산해 최대 max_articles 건 반환.
    섹션별 max_page 를 SECTION_CONFIGS에서 가져와 사용.
    """
    results: list[Article] = []
    seen_ids: set[str] = set()

    for config in SECTION_CONFIGS:
        # 섹션마다 새 Session — 이전 섹션의 rate limiting 영향 차단
        with requests.Session() as session:
            session.headers.update(HEADERS)

            section_url = config["url"]
            max_pages = config["max_page"]

            if len(results) >= max_articles:
                break

            for page in range(1, max_pages + 1):
                items = fetch_hankyung_page(session, section_url, page=page)
                if not items:
                    break

                found_any_target = False
                passed_target = False

                for item in items:
                    date, time_ = parse_input_time(item.listed_at)
                    if date is None:
                        continue
                    if date > target_date:
                        continue
                    if date < target_date:
                        passed_target = True
                        break

                    # date == target_date
                    found_any_target = True
                    uid = item.article_id or item.url
                    if uid in seen_ids:
                        continue
                    seen_ids.add(uid)

                    try:
                        soup = get_soup(session, item.url)
                        body = extract_hankyung_body(soup)
                    except Exception:
                        body = ""

                    results.append(Article(
                        index=item.index,
                        article_id=item.article_id,
                        category="경제",
                        title=item.title,
                        url=item.url,
                        listed_at=item.listed_at,
                        published_at=f"{date} {time_}" if time_ else date,
                        published_date=date,
                        published_time=time_,
                        body=body,
                    ))

                    if len(results) >= max_articles:
                        break

                if passed_target or len(results) >= max_articles:
                    break
                # 조기 중단 제거 — 과거 날짜는 많은 페이지 필요

    return results


def print_summary(articles: Iterable[Article], date: str) -> None:
    print(f"\n[경제] {date} 수집 결과: {len(list(articles))}건")
    for a in articles:
        print(f"  [{a.index:02d}] {a.title[:50]} | {a.published_at}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="한국경제 거시경제·경제정책 섹션 수집")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--json", default="hankyung_articles.json")
    args = parser.parse_args()

    articles = collect_economy_by_date(args.date, max_articles=args.max)

    output = {
        "date": args.date,
        "count": len(articles),
        "articles": [asdict(a) for a in articles],
    }
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print_summary(articles, args.date)
    print(f"JSON 저장: {args.json}")
