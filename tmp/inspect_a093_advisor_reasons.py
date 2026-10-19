"""Read-only inspection of A093's valid DE opportunities and decision reasons."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advisor_original_criteria_analysis as audit


RUN = audit.EXPERIMENTS / audit.NAMES["personal"]


def main() -> None:
    parent = audit.load_states("parent")
    states = audit.load_states("personal")
    turns = {
        int(row["turn"]): row
        for row in audit.read_csv(RUN / "agent_turns.csv")
        if row["agent_id"] == "A093" and "2026-05-06" <= row["date"] <= "2026-07-09"
    }
    rows = [
        row for row in audit.read_csv(RUN / "exchange_fills.csv")
        if row["agent_id"] == "A093" and "2026-05-06" <= row["date"] <= "2026-07-09"
    ]
    valid = []
    for row in rows:
        turn = int(row["turn"])
        prior = states.get(("A093", turn - 1), parent.get(("A093", turn - 1)))
        assert prior is not None
        holdings = int(prior["positions"][0]["quantity"]) if prior["positions"] else 0
        avg_cost = float(prior["positions"][0]["avg_cost"]) if prior["positions"] else 0.0
        cash = float(prior["cash"])
        price = float(row["executed_price"])
        if holdings == 0 or int(0.5 * cash / price) < 1 or abs(price - avg_cost) < 1e-9:
            continue
        side = "gain" if price > avg_cost else "loss"
        turn_row = turns[turn]
        assert turn_row["action"] == row["action"]
        assert int(turn_row["quantity"]) == int(row["quantity"])
        reason = turn_row["decision_reason"]
        valid.append({
            "date": row["date"], "turn": turn, "side": side,
            "action": row["action"], "price": price,
            "avg_cost": avg_cost, "quantity": int(row["quantity"]),
            "reason": reason,
            "advisor_term": bool(re.search(r"어드바이저|조언|처분효과", reason)),
            "profit_term": bool(re.search(r"차익|익절|이익|수익|고점|과열|목표", reason)),
            "fundamental_term": bool(re.search(r"내재가치|실적|업황|가치|위험|리스크|노조", reason)),
        })
    for side in ("gain", "loss"):
        for action in ("sell", "buy"):
            group = [row for row in valid if row["side"] == side and row["action"] == action]
            print("GROUP", side, action, len(group), {
                key: sum(row[key] for row in group)
                for key in ("advisor_term", "profit_term", "fundamental_term")
            })
    gain_sells = [row for row in valid if row["side"] == "gain" and row["action"] == "sell"]
    twenty = [row for row in gain_sells if re.search(r"20\s*%|20\s*퍼센트", row["reason"])]
    print("GAIN_SELL_20PCT_MENTIONS", len(twenty), [
        (row["date"], row["turn"], round((row["price"] / row["avg_cost"] - 1) * 100, 2))
        for row in twenty
    ])
    print("GAIN_SELL_POSITION_RETURN_RANGE_PCT", round(min((row["price"] / row["avg_cost"] - 1) * 100 for row in gain_sells), 2),
          round(max((row["price"] / row["avg_cost"] - 1) * 100 for row in gain_sells), 2))
    for row in valid:
        if row["side"] == "gain" and row["action"] == "sell":
            print("GAIN_SELL", row["date"], row["turn"], row["quantity"],
                  f"price={row['price']:.0f}", f"cost={row['avg_cost']:.0f}", row["reason"])
        if row["side"] == "loss" and row["action"] == "buy" and row["advisor_term"]:
            print("LOSS_BUY_ADVISOR", row["date"], row["turn"], row["quantity"],
                  f"price={row['price']:.0f}", f"cost={row['avg_cost']:.0f}", row["reason"])


if __name__ == "__main__":
    main()
