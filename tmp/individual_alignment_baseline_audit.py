"""Read-only recomputation of the paper's 87-day alignment comparison."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "outputs/experiments/ADVISOR_MAIN_FROM_SCRATCH_PARENT_20260923"
NOA = ROOT / "outputs/experiments/ADVISOR_MAIN_CONT_OFF_20260925"
DERIVED = ROOT / "outputs/experiments/derived/advisor_baseline_to_20260710/provisional_direction_validation"
INPUTS = []


def read(path):
    INPUTS.append(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


value_net, volume_net, keys = defaultdict(float), defaultdict(float), set()
agent_ids, full_dates = set(), set()
for run in (PRE, NOA):
    meta_path = run / "run_metadata.json"
    INPUTS.append(meta_path)
    meta = json.loads(meta_path.read_text())
    assert meta["community_mode"] == "on" and meta["advisor_mode"] == "off"
    for row in read(run / "exchange_fills.csv"):
        if not "2026-02-27" <= row["date"] <= "2026-07-09":
            continue
        key = (row["date"], row["subturn"], row["agent_id"])
        assert key not in keys
        keys.add(key)
        agent_ids.add(row["agent_id"])
        full_dates.add(row["date"])
        assert row["status"] == "filled" and row["action"] in ("buy", "sell")
        side = 1 if row["action"] == "buy" else -1
        qty = float(row["quantity"])
        volume_net[row["date"]] += side * qty
        value_net[row["date"]] += side * qty * float(row["executed_price"])
assert len(keys) == 18000 and len(agent_ids) == 100 and len(full_dates) == 90
assert all((date, subturn, agent) in keys
           for date in full_dates for subturn in ("am", "pm") for agent in agent_ids)
evaluation_dates = sorted(full_dates)[3:]
assert len(evaluation_dates) == 87 and evaluation_dates[0] == "2026-03-05"

stock = read(ROOT / "data/stock_data.csv")
returns, prior_return, prior_date = {}, {}, {}
for i, row in enumerate(stock):
    date = row["date"]
    if i > 0:
        prior_date[date] = stock[i - 1]["date"]
        returns[date] = float(row["close"]) / float(stock[i - 1]["close"]) - 1
    if i > 1:
        prior_return[date] = returns[prior_date[date]]

out = {
    "parent_run": PRE.name,
    "no_advice_branch": NOA.name,
    "simulation_window": ["2026-02-27", "2026-07-09"],
    "evaluation_window": [evaluation_dates[0], evaluation_dates[-1]],
    "burn_in_dates": sorted(full_dates)[:3],
    "canonical_fill_count": len(keys),
    "evaluation_days": len(evaluation_dates),
    "first_lagged_observation_date": prior_date[evaluation_dates[0]],
    "publication_status": "provisional; not a replacement for the run integrity gate",
    "dimensions": {},
}

for measure, canonical in (("value", value_net), ("volume", volume_net)):
    rows = [row for row in read(DERIVED / f"daily_comparison_{measure}.csv")
            if row["date"] in evaluation_dates]
    assert [row["date"] for row in rows] == evaluation_dates
    actual = {row["Date"].replace("/", "-"): float(row["Individuals"])
              for row in read(ROOT / "validation" / f"data_trading_{measure}.csv")}
    observed = np.array([float(row["Individuals"]) for row in rows])
    simulated = np.array([float(row["llm_net"]) for row in rows])
    assert all(np.isclose(simulated[i], canonical[row["date"]], rtol=0, atol=1e-3)
               and observed[i] == actual[row["date"]]
               and abs(float(row["market_return"]) - returns[row["date"]]) < 1e-12
               for i, row in enumerate(rows))
    labels = np.sign(observed)
    assert np.all(labels != 0)
    lag_return = np.sign([prior_return[row["date"]] for row in rows])
    predictors = {
        "LLM": np.sign(simulated),
        "Always net buy": np.ones(len(rows)),
        "Lagged return": lag_return,
        "Contrarian return": -lag_return,
        "Lagged flow": np.sign([actual[prior_date[row["date"]]] for row in rows]),
    }
    metrics = {}
    for name, predicted in predictors.items():
        matched = predicted == labels
        buy = matched[labels > 0].mean()
        sell = matched[labels < 0].mean()
        metrics[name] = {
            "matches": int(matched.sum()),
            "agreement_percent": float(100 * matched.mean()),
            "balanced_accuracy_percent": float(50 * (buy + sell)),
            "buy_recall_percent": float(100 * buy),
            "sell_recall_percent": float(100 * sell),
            "flat_predictions": int((predicted == 0).sum()),
        }
    out["dimensions"][measure] = {
        "actual_buy_days": int((labels > 0).sum()),
        "actual_sell_days": int((labels < 0).sum()),
        "pearson_r": float(np.corrcoef(simulated, observed)[0, 1]),
        "metrics": metrics,
    }

out["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in dict.fromkeys(INPUTS)}
output = ROOT / "output/analysis/individual_alignment_87day_baseline_audit.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps({"output": str(output), "dimensions": out["dimensions"]}, indent=2))
