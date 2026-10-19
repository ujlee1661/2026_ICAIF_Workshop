"""
Claude Code CLI sub-agent — 뉴스 기사 카테고리별 200~250자 요약.

별도 API 키 없이 Claude Code 한도로 실행.
`claude -p "..."` 를 병렬 subprocess로 호출.

사용:
    from summarize import summarize_articles
    summaries = summarize_articles(["본문1", "본문2"], category="종목")
    # → ["요약1", "요약2"]
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MODEL = "claude-haiku-4-5-20251001"   # 가장 저렴한 모델
TARGET_MIN = 200        # 목표 하한
TARGET_MAX = 250        # 목표 상한
HARD_CAP = 280          # 절대 상한 (truncate 기준)
MAX_BODY_INPUT = 2500   # CLI에 넘길 본문 최대 길이
MAX_WORKERS = 4         # 병렬 subprocess 수


def _find_claude() -> str:
    """claude CLI 실행 파일 경로 탐색 (PATH에 없을 수 있음)."""
    found = shutil.which("claude")
    if found:
        return found
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "claude"   # 최후: PATH에 의존


CLAUDE_BIN = _find_claude()


# ── 카테고리별 프롬프트 ──────────────────────────────────────────────────────

_COMMON_TAIL = (
    "\n\n분량은 한국어 {min}~{max}자를 지켜라({max}자를 넘기지 마라). "
    "어떤 내용의 기사가 오더라도 거부하거나 되묻지 말고 항상 요약문만 출력하라. "
    "요약문 한 단락만 출력하고, 머리말·설명·질문·목록·마크다운·따옴표 등 "
    "다른 어떤 텍스트도 붙이지 마라.\n\n기사:\n{body}"
)

_PROMPTS = {
    "종목": (
        "다음 기사를 삼성전자 관점에서 요약하라. "
        "삼성전자의 사업·실적·전략·투자·인사·주가 등 회사와 직접 관련된 내용과 "
        "구체적 수치(금액·증감률·점유율 등)를 우선 담고, "
        "삼성전자에 미치는 영향이나 의미가 드러나도록 작성하라. "
        "삼성전자 언급이 적은 기사라면 기사 핵심을 요약하되 시장·산업 함의를 담아라."
    ),
    "섹터": (
        "다음 기사를 산업·시장 관점에서 요약하라. "
        "반도체·전자를 비롯한 산업 업황 흐름, 주요 기업 동향, "
        "수급·가격·투자 등 시장 전반의 움직임과 구체적 수치를 중심으로 작성하라."
    ),
    "경제": (
        "다음 기사를 거시경제 관점에서 요약하라. "
        "금리·환율·물가·수출·성장률·재정·정책 등 거시 변수와 그 방향성, "
        "시장·경기에 미치는 함의, 구체적 수치를 중심으로 작성하라."
    ),
}
_DEFAULT_PROMPT = (
    "다음 기사를 핵심 사실과 구체적 수치 중심으로 요약하라."
)


def _build_prompt(category: str, body: str) -> str:
    head = _PROMPTS.get(category, _DEFAULT_PROMPT)
    tail = _COMMON_TAIL.format(min=TARGET_MIN, max=TARGET_MAX, body=body[:MAX_BODY_INPUT])
    return head + tail


# ── 출력 정제 ────────────────────────────────────────────────────────────────

def _clean_output(text: str) -> str:
    """CLI 출력에서 요약 본문만 추출 (부가 설명·마크다운 제거)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cleaned = []
    for ln in lines:
        if ln.startswith(("- ", "* ", "#", "**", "주요", "요약")):
            continue
        cleaned.append(ln)
    body = " ".join(cleaned) if cleaned else " ".join(lines)
    return body.strip()


def _truncate(text: str) -> str:
    """HARD_CAP 이내로 자르되 문장 중간에 끊기지 않게 처리."""
    if len(text) <= HARD_CAP:
        return text
    cut = text[:HARD_CAP]
    for sep in ("다.", "다!", "다?", "요.", "임.", "됨.", "함."):
        idx = cut.rfind(sep)
        if idx > HARD_CAP * 0.5:
            return cut[: idx + len(sep)]
    return cut.rstrip() + "…"


def _fallback(body: str) -> str:
    """CLI 실패 시 본문 앞부분 반환."""
    return _truncate(re.sub(r"\s+", " ", (body or "")).strip())


def _summarize_one(body: str, category: str) -> str:
    """claude CLI 로 기사 하나 요약."""
    if not body or len(body) < 50:
        return _fallback(body)

    prompt = _build_prompt(category, body)
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--model", MODEL, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=90,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,   # stdin 대기 경고 방지
        )
        if result.returncode == 0 and result.stdout.strip():
            return _truncate(_clean_output(result.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    return _fallback(body)


def summarize_articles(bodies: list[str], category: str = "") -> list[str]:
    """
    기사 본문 리스트를 받아 카테고리별 프롬프트로 200~250자 요약 반환.
    category: "종목" | "섹터" | "경제" (그 외는 일반 프롬프트).
    병렬 처리 (MAX_WORKERS개 동시). claude CLI 실패 시 본문 앞부분으로 대체.
    """
    if not bodies:
        return []

    results = [""] * len(bodies)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(_summarize_one, body, category): i
            for i, body in enumerate(bodies)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = _fallback(bodies[idx])

    return results
