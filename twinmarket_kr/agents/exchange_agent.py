from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config
from twinmarket_kr.db.connection import connect, init_sim_db


@dataclass(slots=True)
class Order:
    stock_code: str
    user_id: str
    direction: str
    quantity: int
    price: float
    timestamp: float


def _as_order(value: Order | dict[str, Any]) -> Order:
    if isinstance(value, Order):
        return value
    return Order(
        stock_code=value.get("stock_code", config.STOCK_CODE),
        user_id=value["user_id"],
        direction=value["direction"],
        quantity=int(value["quantity"]),
        price=float(value.get("price", 0)),
        timestamp=float(value.get("timestamp", 0)),
    )


def _transaction(order: Order, executed_price: float, quantity: int) -> dict[str, Any]:
    return {
        "stock_code": order.stock_code,
        "user_id": order.user_id,
        "agent_id": order.user_id,
        "direction": order.direction,
        "action": order.direction,
        "executed_price": executed_price,
        "executed_quantity": int(quantity),
        "quantity": int(quantity),
        "status": "filled",
        "fee": 0.0,
        "timestamp": order.timestamp,
    }


class ExchangeAgent:
    def __init__(self, db_path: Path | str = config.SIM_DB) -> None:
        self.db_path = Path(db_path)
        init_sim_db(self.db_path)

    @staticmethod
    def get_allowed_actions(portfolio: dict[str, Any], announced_price: float) -> list[str]:
        max_buy_cash = float(portfolio.get("cash", 0.0)) * config.MAX_SINGLE_TRADE_CASH_RATIO
        can_buy = max_buy_cash >= announced_price
        can_sell = int(portfolio.get("position", 0)) >= 1
        allowed = []
        if can_buy:
            allowed.append("buy")
        if can_sell:
            allowed.append("sell")
        return allowed

    def execute_binary_orders(
        self,
        orders: list[Order | dict[str, Any]],
        *,
        announced_price: float,
        portfolios: dict[str, dict[str, Any]],
    ) -> tuple[float, int, list[dict[str, Any]]]:
        transactions = []
        for raw_order in orders:
            order = _as_order(raw_order)
            portfolio = portfolios.get(order.user_id)
            if portfolio is None:
                raise ValueError(f"portfolio snapshot missing for {order.user_id}")
            allowed = self.get_allowed_actions(portfolio, announced_price)
            if not allowed:
                raise ValueError(f"no feasible action for {order.user_id} at {announced_price}")
            if order.direction not in allowed:
                raise ValueError(f"invalid action for {order.user_id}: {order.direction} not in {allowed}")
            if order.quantity < 1:
                raise ValueError(f"invalid quantity for {order.user_id}: {order.quantity}")
            if order.direction == "buy":
                max_buy_cash = float(portfolio.get("cash", 0.0)) * config.MAX_SINGLE_TRADE_CASH_RATIO
                max_buy_quantity = int(max_buy_cash // announced_price)
                if order.quantity > max_buy_quantity:
                    raise ValueError(
                        f"buy quantity exceeds single-trade cash limit for {order.user_id}: "
                        f"{order.quantity} > {max_buy_quantity}"
                    )
            else:
                holding = int(portfolio.get("position", 0))
                if order.quantity > holding:
                    raise ValueError(f"sell quantity exceeds holdings for {order.user_id}: {order.quantity} > {holding}")
            transactions.append(_transaction(order, announced_price, order.quantity))
        volume = sum(tx["quantity"] for tx in transactions)
        return announced_price, volume, transactions

    def process_daily_orders(
        self,
        orders: list[Order | dict[str, Any]],
        real_prices: dict[str, float],
        last_real_prices: dict[str, float],
        *,
        current_date: str,
        day_number: int,
        persist: bool = True,
        portfolios: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        stock_orders: dict[str, dict[str, list[Order]]] = defaultdict(lambda: {"buy": [], "sell": []})
        for raw_order in orders:
            order = _as_order(raw_order)
            if order.direction not in {"buy", "sell"}:
                continue
            stock_orders[order.stock_code][order.direction].append(order)

        results: dict[str, dict[str, Any]] = {}
        for stock_code in sorted(set(real_prices) | set(stock_orders)):
            real_price = float(real_prices[stock_code])
            buy = stock_orders[stock_code]["buy"]
            sell = stock_orders[stock_code]["sell"]
            announced_price, volume, transactions = self.execute_binary_orders(
                buy + sell,
                announced_price=real_price,
                portfolios=portfolios or {},
            )
            results[stock_code] = {
                "announced_price": announced_price,
                "close_price": announced_price,
                "volume": volume,
                "transactions": transactions,
            }
            if persist:
                self.save_trading_details(current_date, stock_code, transactions)
        return results

    def save_trading_details(self, date: str, stock_code: str, transactions: list[dict[str, Any]]) -> None:
        with connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO TradingDetails (
                    date, stock_id, user_id, trading_direction, price, volume
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        date,
                        stock_code,
                        tx["user_id"],
                        tx["direction"],
                        tx["executed_price"],
                        tx["executed_quantity"],
                    )
                    for tx in transactions
                ],
            )
            conn.commit()
