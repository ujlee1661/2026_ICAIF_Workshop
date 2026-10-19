from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path
from statistics import stdev
from typing import Any

import config
from twinmarket_kr.db.connection import connect, init_sim_db


DATE_CANDIDATES = ("date", "trade_date", "datetime", "timestamp", "날짜")
OPEN_CANDIDATES = ("open", "open_price", "open_hfq", "시가")
HIGH_CANDIDATES = ("high", "high_price", "high_hfq", "고가")
LOW_CANDIDATES = ("low", "low_price", "low_hfq", "저가")
CLOSE_CANDIDATES = ("close", "close_price", "close_hfq", "종가")
VOLUME_CANDIDATES = ("volume", "vol", "거래량")
MA5_CANDIDATES = ("ma5", "ma_hfq_5", "ma_5")
MA20_CANDIDATES = ("ma20", "ma_hfq_20", "ma_20")
PCT_CHG_CANDIDATES = ("pct_chg", "change_pct", "returns", "return")


def _pick(columns: list[str], candidates: tuple[str, ...], *, required: bool = False) -> str | None:
    normalized = {col.lower().strip(): col for col in columns}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    if required:
        raise ValueError(f"required column not found. candidates={candidates}, columns={columns}")
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    return float(text)


def _returns_for_volatility(closes: list[float], index: int, window: int = 20) -> float | None:
    if index < 1:
        return None
    start = max(1, index - window + 1)
    returns = []
    for i in range(start, index + 1):
        if closes[i - 1] > 0 and closes[i] > 0:
            returns.append(math.log(closes[i] / closes[i - 1]))
    if len(returns) < 2:
        return None
    return stdev(returns)


def load_daily_price_csv(csv_path: Path | str = config.STOCK_DATA_CSV) -> dict[str, dict[str, float]]:
    """Load date -> {"open": price, "close": price} reference prices."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"daily stock data csv not found: {path}")
    result: dict[str, dict[str, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        date_col = _pick(columns, DATE_CANDIDATES, required=True)
        open_col = _pick(columns, OPEN_CANDIDATES)
        close_col = _pick(columns, CLOSE_CANDIDATES, required=True)
        for row in reader:
            day = str(row.get(date_col) or "").strip()
            if not day:
                continue
            close = _to_float(row.get(close_col))
            if close is None:
                continue
            open_price = _to_float(row.get(open_col)) if open_col else close
            result[day] = {
                "open": float(open_price if open_price is not None else close),
                "close": float(close),
            }
    return result


class FundamentalAgent:
    def __init__(self, db_path: Path | str = config.SIM_DB) -> None:
        self.db_path = Path(db_path)
        init_sim_db(self.db_path)
        self._ensure_columns()

    def load_stock_data_csv(
        self,
        csv_path: Path | str = config.STOCK_DATA_CSV,
        *,
        stock_code: str = config.STOCK_CODE,
    ) -> int:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"stock data csv not found: {path}")

        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                return 0
            columns = reader.fieldnames or []

        date_col = _pick(columns, DATE_CANDIDATES, required=True)
        close_col = _pick(columns, CLOSE_CANDIDATES, required=True)
        open_col = _pick(columns, OPEN_CANDIDATES)
        high_col = _pick(columns, HIGH_CANDIDATES)
        low_col = _pick(columns, LOW_CANDIDATES)
        volume_col = _pick(columns, VOLUME_CANDIDATES)
        ma5_col = _pick(columns, MA5_CANDIDATES)
        ma20_col = _pick(columns, MA20_CANDIDATES)
        pct_col = _pick(columns, PCT_CHG_CANDIDATES)

        rows = sorted(rows, key=lambda row: str(row[date_col]))
        closes = [_to_float(row[close_col]) for row in rows]
        if any(close is None for close in closes):
            raise ValueError(f"close column contains empty values: {close_col}")
        close_values = [float(close) for close in closes]
        volumes = [_to_float(row[volume_col]) if volume_col else None for row in rows]

        records = []
        for idx, row in enumerate(rows):
            close = close_values[idx]
            prev_close = close_values[idx - 1] if idx > 0 else None
            pct_chg = _to_float(row[pct_col]) if pct_col else None
            if pct_chg is None and prev_close:
                pct_chg = (close - prev_close) / prev_close
            volume = volumes[idx]
            prev_volume = volumes[idx - 1] if idx > 0 else None
            volume_chg = None
            if volume is not None and prev_volume not in {None, 0}:
                volume_chg = (volume - float(prev_volume)) / float(prev_volume)
            ma5 = _to_float(row[ma5_col]) if ma5_col else None
            if ma5 is None and idx >= 4:
                ma5 = sum(close_values[idx - 4 : idx + 1]) / 5
            ma20 = _to_float(row[ma20_col]) if ma20_col else None
            if ma20 is None and idx >= 19:
                ma20 = sum(close_values[idx - 19 : idx + 1]) / 20
            records.append(
                (
                    str(row[date_col]),
                    stock_code,
                    _to_float(row[open_col]) if open_col else None,
                    _to_float(row[high_col]) if high_col else None,
                    _to_float(row[low_col]) if low_col else None,
                    close,
                    volume,
                    pct_chg,
                    volume_chg,
                    ma5,
                    ma20,
                    _returns_for_volatility(close_values, idx),
                )
            )

        with connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO StockData (
                    date, stock_id, open_price, high_price, low_price, close_price,
                    volume, pct_chg, volume_chg, ma5, ma20, volatility_20d
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()
        return len(records)

    def get_market_features(self, date: str, stock_code: str = config.STOCK_CODE) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM StockData
                WHERE date = ? AND stock_id = ?
                """,
                (date, stock_code),
            ).fetchone()
        if row is None:
            raise KeyError(f"market features not found for {stock_code} on {date}")
        return {
            "ticker": stock_code,
            "close": row["close_price"],
            "pct_chg": row["pct_chg"],
            "volume_chg": row["volume_chg"],
            "ma5": row["ma5"],
            "ma20": row["ma20"],
            "volatility_20d": row["volatility_20d"],
        }

    def get_daily_prices(self, date: str, stock_code: str = config.STOCK_CODE) -> dict[str, float]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT open_price, high_price, low_price, close_price
                FROM StockData
                WHERE date = ? AND stock_id = ?
                """,
                (date, stock_code),
            ).fetchone()
        if row is None:
            raise KeyError(f"daily prices not found for {stock_code} on {date}")
        return {
            "open": float(row["open_price"] if row["open_price"] is not None else row["close_price"]),
            "high": float(row["high_price"] if row["high_price"] is not None else row["close_price"]),
            "low": float(row["low_price"] if row["low_price"] is not None else row["close_price"]),
            "close": float(row["close_price"]),
        }

    def _ensure_columns(self) -> None:
        with connect(self.db_path) as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(StockData)").fetchall()}
            if "volume_chg" not in columns:
                conn.execute("ALTER TABLE StockData ADD COLUMN volume_chg REAL")
                conn.commit()
