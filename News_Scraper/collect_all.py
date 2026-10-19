"""
전체 뉴스 수집 오케스트레이터.

2025-01-01부터 오늘까지 날짜별로 세 카테고리를 수집하고
Claude Haiku CLI로 카테고리별 200~250자 요약 후 저장.

출력 파일 (프로젝트 루트 data/):
    samsung_news.pkl       — 종목 뉴스 (카테고리별 보관용)
    sector_news.pkl        — 섹터 뉴스
    economy_news.pkl       — 경제 뉴스
    samsung_news_raw.pkl   — 세 카테고리 통합 (prepare_news 입력용, config 경로)
    collection_progress.md — 진행 상황 (주차별 일별 건수 표 + 재개 지점)

실행:
    python collect_all.py
    python collect_all.py --start 2025-01-01 --end 2025-03-31
    python collect_all.py --resume   # 이미 수집된 날짜 건너뜀
"""
from __future__ import annotations

import argparse
import sys
import io
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

import pandas as pd

from scrape_mk_stock_playwright import collect_stock_by_date
from scrape_mk_sector_playwright import collect_sector_by_date
from scrape_hankyung import collect_economy_by_date
from summarize import summarize_articles

MAX_PER_CATEGORY = 20
REQUEST_DELAY = 1.5
DATE_DELAY = 2.0

# 카테고리별 보관 파일
PKL_MAP = {
    "종목": DATA_DIR / "samsung_news.pkl",
    "섹터": DATA_DIR / "sector_news.pkl",
    "경제": DATA_DIR / "economy_news.pkl",
}
# 통합 파일 (config.SAMSUNG_NEWS_RAW_PKL 과 동일 경로) — prepare_news 입력
MERGED_PKL = DATA_DIR / "samsung_news_raw.pkl"
PROGRESS_MD = DATA_DIR / "collection_progress.md"

# pkl 저장 컬럼 순서 (prepare_news 호환: title/date/time/category/summary/body 모두 인식)
COLUMNS = ["date", "time", "title", "category", "summary", "body", "source", "url"]
WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
BAD_SUMMARY_MARKERS = {"사진확대", "사진 확대"}
EXCLUDED_TITLE_PATTERNS = (
    re.compile(r"^\s*\[?표\]?\s*외국\s*환율\s*고시표?\s*$"),
)


# ── 날짜 헬퍼 ────────────────────────────────────────────────────────────────

def trading_days(start: str, end: str) -> list[str]:
    """start ~ end 사이의 평일(월~금) 목록 반환."""
    days: list[str] = []
    current = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    while current <= end_date:
        if current.weekday() < 5:
            days.append(str(current))
        current += timedelta(days=1)
    return days


# ── pkl 헬퍼 ─────────────────────────────────────────────────────────────────

def load_pkl(path: Path) -> pd.DataFrame:
    return pd.read_pickle(path) if path.exists() else pd.DataFrame()


def save_pkl(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)


def clean_summary(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if re.sub(r"\s+", "", text) in BAD_SUMMARY_MARKERS:
        return ""
    text = re.sub(r"\s*사진\s*확대\s*", " ", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    if re.sub(r"\s+", "", text) in BAD_SUMMARY_MARKERS:
        return ""
    return text


def is_excluded_title(title: object) -> bool:
    text = str(title or "").strip()
    return any(pattern.search(text) for pattern in EXCLUDED_TITLE_PATTERNS)


def clean_news_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cleaned = df.copy()
    if "summary" in cleaned.columns:
        cleaned["summary"] = cleaned["summary"].map(clean_summary)
        cleaned = cleaned[cleaned["summary"].astype(str).str.strip().ne("")]
    if "title" in cleaned.columns:
        cleaned = cleaned[~cleaned["title"].map(is_excluded_title)]
    return cleaned


def collected_dates() -> set[str]:
    """이미 수집된 날짜 집합 (세 파일 중 하나라도 있으면 수집 완료로 간주)."""
    dates: set[str] = set()
    for pkl in PKL_MAP.values():
        df = load_pkl(pkl)
        if not df.empty and "date" in df.columns:
            dates |= set(df["date"].astype(str).unique())
    return dates


# ── 수집 함수 ────────────────────────────────────────────────────────────────

def _to_rows(articles, category: str, target_date: str) -> list[dict]:
    return [
        {
            "date":     a.published_date or target_date,
            "time":     a.published_time or "",
            "title":    a.title,
            "category": category,                       # ★ prepare_news 분류용
            "summary":  "",                             # summarize 단계에서 채움
            "body":     a.body,
            "source":   "mk" if category in ("종목", "섹터") else "hankyung",
            "url":      a.url,
        }
        for a in articles
    ]


def collect_day(target_date: str) -> dict[str, list[dict]]:
    """하루치 세 카테고리 수집. 반환: {카테고리: rows 리스트}"""
    rows: dict[str, list[dict]] = {"종목": [], "섹터": [], "경제": []}

    try:
        stock = collect_stock_by_date(target_date, max_articles=MAX_PER_CATEGORY, fetch_body=True)
        rows["종목"] = _to_rows(stock, "종목", target_date)
        print(f"  종목: {len(rows['종목'])}건")
    except Exception as e:
        print(f"  종목 실패: {e}")
    time.sleep(REQUEST_DELAY)

    try:
        sector = collect_sector_by_date(target_date, max_articles=MAX_PER_CATEGORY, fetch_body=True)
        rows["섹터"] = _to_rows(sector, "섹터", target_date)
        print(f"  섹터: {len(rows['섹터'])}건")
    except Exception as e:
        print(f"  섹터 실패: {e}")
    time.sleep(REQUEST_DELAY)

    try:
        economy = collect_economy_by_date(target_date, max_articles=MAX_PER_CATEGORY)
        rows["경제"] = _to_rows(economy, "경제", target_date)
        print(f"  경제: {len(rows['경제'])}건")
    except Exception as e:
        print(f"  경제 실패: {e}")

    return rows


def summarize_day(rows_by_cat: dict[str, list[dict]]) -> None:
    """카테고리별 프롬프트로 기사 본문을 Claude CLI 요약 (in-place 수정)."""
    total = sum(len(v) for v in rows_by_cat.values())
    if total == 0:
        return

    print(f"  요약 중 ({total}건)...", end=" ", flush=True)
    for category, rows in rows_by_cat.items():
        if not rows:
            continue
        bodies = [r["body"] for r in rows]
        summaries = summarize_articles(bodies, category=category)
        for r, s in zip(rows, summaries):
            r["summary"] = clean_summary(s)
    print("완료")


def append_to_pkl(rows_by_cat: dict[str, list[dict]]) -> None:
    """카테고리별 pkl에 추가 저장. url 기준 중복 제거."""
    for cat, rows in rows_by_cat.items():
        if not rows:
            continue
        pkl_path = PKL_MAP[cat]
        existing = load_pkl(pkl_path)
        combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        combined = clean_news_df(combined)
        combined = combined.drop_duplicates(subset=["url"])
        # 컬럼 순서 정렬 (없는 컬럼 보강)
        for col in COLUMNS:
            if col not in combined.columns:
                combined[col] = ""
        combined = combined[COLUMNS].sort_values(["date", "time"]).reset_index(drop=True)
        save_pkl(combined, pkl_path)


def rebuild_merged_pkl() -> dict[str, int]:
    """카테고리별 3파일을 합쳐 통합 pkl 생성 (prepare_news 입력). 카테고리별 건수 반환."""
    frames = []
    counts: dict[str, int] = {}
    for cat, pkl in PKL_MAP.items():
        df = load_pkl(pkl)
        counts[cat] = len(df)
        if not df.empty:
            frames.append(df)
    if frames:
        merged = pd.concat(frames, ignore_index=True)
        merged = clean_news_df(merged)
        merged = merged.drop_duplicates(subset=["url"])
        merged = merged.sort_values(["date", "category", "time"]).reset_index(drop=True)
        # prepare_news 는 list of dict 를 기대하므로 records 로 저장
        import pickle
        MERGED_PKL.parent.mkdir(parents=True, exist_ok=True)
        with MERGED_PKL.open("wb") as f:
            pickle.dump(merged.to_dict("records"), f)
    return counts


# ── 진행 상황 MD ─────────────────────────────────────────────────────────────

def write_progress_md(start: str, end: str, all_days: list[str]) -> None:
    """주차별 일별 수집 건수 표 + 재개 지점을 MD로 저장."""
    # 카테고리별 날짜별 건수 집계
    per_date: dict[str, dict[str, int]] = {}
    for cat, pkl in PKL_MAP.items():
        df = load_pkl(pkl)
        if df.empty:
            continue
        for d, n in df.groupby(df["date"].astype(str)).size().items():
            per_date.setdefault(d, {"종목": 0, "섹터": 0, "경제": 0})[cat] = int(n)

    done = sorted(per_date.keys())
    total_days = len(all_days)
    done_count = len([d for d in all_days if d in per_date])
    pct = (done_count / total_days * 100) if total_days else 0.0
    last_done = done[-1] if done else "(없음)"
    # 다음 재개 지점 = all_days 중 아직 수집 안 된 첫 날
    remaining = [d for d in all_days if d not in per_date]
    next_date = remaining[0] if remaining else "(전체 완료)"

    lines = [
        "# 뉴스 수집 진행 상황",
        "",
        f"- **마지막 업데이트**: {datetime.now():%Y-%m-%d %H:%M}",
        f"- **수집 기간**: {start} ~ {end}",
        f"- **전체 진행률**: {pct:.1f}% ({done_count}/{total_days}일)",
        f"- **마지막 완료 날짜**: {last_done}",
        f"- **재개 지점(다음 수집 날짜)**: {next_date}",
        "",
        "> 중단 후 이어서 수집하려면: `python collect_all.py --resume`",
        "",
        "## 주차별 수집 현황",
        "",
    ]

    # 주차별 그룹핑 (ISO week)
    weeks: dict[str, list[str]] = {}
    for d in all_days:
        iso = date.fromisoformat(d).isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        weeks.setdefault(wk, []).append(d)

    for wk in sorted(weeks):
        wk_days = sorted(weeks[wk])
        # 수집된 날이 하나도 없는 미래 주는 생략
        if not any(d in per_date for d in wk_days):
            continue
        lines.append(f"### {wk}  ({wk_days[0]} ~ {wk_days[-1]})")
        lines.append("")
        lines.append("| 날짜 | 요일 | 종목 | 섹터 | 경제 | 합계 | 상태 |")
        lines.append("|------|------|-----:|-----:|-----:|-----:|------|")
        for d in wk_days:
            wd = WEEKDAY_KR[date.fromisoformat(d).weekday()]
            if d in per_date:
                c = per_date[d]
                tot = c["종목"] + c["섹터"] + c["경제"]
                lines.append(f"| {d} | {wd} | {c['종목']} | {c['섹터']} | {c['경제']} | {tot} | ✅ |")
            else:
                lines.append(f"| {d} | {wd} | - | - | - | - | ⬜ |")
        lines.append("")

    PROGRESS_MD.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_MD.write_text("\n".join(lines), encoding="utf-8")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--resume", action="store_true", help="이미 수집된 날짜 건너뜀")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_days = trading_days(args.start, args.end)
    done_dates = collected_dates() if args.resume else set()
    days = [d for d in all_days if d not in done_dates]

    print(f"수집 대상: {len(days)}일 (전체 {len(all_days)}일, {args.start} ~ {args.end})")
    if args.resume and done_dates:
        print(f"  이미 수집된 날짜 {len(done_dates)}일 건너뜀")

    for i, target_date in enumerate(days, 1):
        pct = i / len(days) * 100
        wd = WEEKDAY_KR[date.fromisoformat(target_date).weekday()]
        print(f"\n[{i}/{len(days)} · {pct:.1f}%] {target_date}({wd}) 수집 중...")

        rows_by_cat = collect_day(target_date)
        total = sum(len(v) for v in rows_by_cat.values())
        print(f"  합계: {total}건")

        if total > 0:
            summarize_day(rows_by_cat)
            append_to_pkl(rows_by_cat)

        # 매일 통합 pkl + 진행상황 MD 갱신 (중단 대비 중간 저장)
        counts = rebuild_merged_pkl()
        write_progress_md(args.start, args.end, all_days)
        print(f"  누적 — 종목:{counts['종목']} 섹터:{counts['섹터']} 경제:{counts['경제']} "
              f"| 진행상황 저장: {PROGRESS_MD.name}")

        time.sleep(DATE_DELAY)

    print("\n=== 수집 완료 ===")
    counts = rebuild_merged_pkl()
    for cat, pkl in PKL_MAP.items():
        print(f"  {cat}: {counts[cat]}건  →  {pkl.name}")
    print(f"  통합: {MERGED_PKL.name}")
    print(f"  진행상황: {PROGRESS_MD.name}")


if __name__ == "__main__":
    main()
