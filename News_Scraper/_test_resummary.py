"""문제됐던 기사 재요약 — 거부 응답·길이 확인."""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
from pathlib import Path
from summarize import summarize_articles

DATA = Path(r"C:\Users\UNIST\Desktop\HeeBeom\MD_File\twinmarket_kr_project\data")

# 섹터: 바이오 기사 (이전에 거부했던 것) 포함 2건
sector = pd.read_pickle(DATA / "sector_news.pkl").head(2)
s = summarize_articles(sector["body"].tolist(), category="섹터")
print("="*70, "\n[섹터]\n", "="*70)
for (_, r), x in zip(sector.iterrows(), s):
    print(f"\n제목: {r['title'][:50]}\n요약({len(x)}자): {x}")

# 종목: 길이 초과했던 첫 기사
stock = pd.read_pickle(DATA / "samsung_news.pkl").head(1)
s2 = summarize_articles(stock["body"].tolist(), category="종목")
print("\n", "="*70, "\n[종목]\n", "="*70)
for (_, r), x in zip(stock.iterrows(), s2):
    print(f"\n제목: {r['title'][:50]}\n요약({len(x)}자): {x}")
