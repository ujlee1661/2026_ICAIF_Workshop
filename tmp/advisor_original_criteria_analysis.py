"""Read-only audit of the three advisor arms against the original 45-day criteria."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "outputs/experiments"
NAMES = {
    "parent": "ADVISOR_MAIN_FROM_SCRATCH_PARENT_20260923",
    "off": "ADVISOR_MAIN_CONT_OFF_20260925",
    "general": "ADVISOR_GENERAL_REPEAT_20261002_TO_20260710",
    "personal": "ADVISOR_PERSONALIZED_V5_20261003_TO_20260710",
}
REPORT = ROOT / "outputs/advisor/advisor_comm_on_20260919/bias45_original_criteria_agent_report.md"
EPS = 1e-12


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * 0.95
    low = math.floor(index)
    high = math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def surge_dates() -> set[str]:
    rows = read_csv(ROOT / "data/stock_data.csv")
    dates = [row["date"] for row in rows]
    closes = [float(row["close"]) for row in rows]
    returns = [closes[i + 1] / closes[i] - 1 for i in range(len(closes) - 1)]
    return {
        dates[i]
        for i in range(254, len(dates))
        if returns[i - 2] > 0
        and returns[i - 2] > percentile_95(returns[i - 254 : i - 2])
    }


def load_states(name: str) -> dict[tuple[str, int], dict]:
    path = EXPERIMENTS / NAMES[name] / "portfolio_updates.jsonl"
    result = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                item = json.loads(line)
                result[(item["agent_id"], int(item["turn"]))] = item["state"]
    return result


def vbsi(buy: float, sell: float) -> float | None:
    total = buy + sell
    return (buy - sell) / total if total > 0 else None


def score_run(name: str, parent_states: dict, surge: set[str]) -> dict[str, dict]:
    states = load_states(name)
    rows = read_csv(EXPERIMENTS / NAMES[name] / "exchange_fills.csv")
    if name != "parent":
        rows = [row for row in rows if "2026-05-06" <= row["date"] <= "2026-07-09"]
    assert len(rows) == 9000, (name, len(rows))
    assert len({row["date"] for row in rows}) == 45
    assert len({row["agent_id"] for row in rows}) == 100
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        assert row["status"] == "filled" and row["action"] in ("buy", "sell")
        assert float(row["fee"]) == 0
        agent = row["agent_id"]
        turn = int(row["turn"])
        prior = states.get((agent, turn - 1))
        if prior is None:
            prior = parent_states.get((agent, turn - 1))
        if prior is None:
            assert name == "parent" and turn == 1
            prior = {"cash": 100_000_000.0, "positions": []}
        positions = prior["positions"]
        shares = int(positions[0]["quantity"]) if positions else 0
        avg_cost = float(positions[0]["avg_cost"]) if positions else 0.0
        cash = float(prior["cash"])
        price = float(row["executed_price"])
        quantity = int(row["quantity"])
        max_buy = math.floor(0.5 * cash / price)
        assert quantity >= 1 and price > 0
        if shares == 0 or max_buy < 1:
            continue
        side = "gain" if price > avg_cost + 1e-9 else "loss" if price < avg_cost - 1e-9 else "flat"
        group = groups[agent]
        if side != "flat":
            group[f"de_{side}_op"].append(1)
            if row["action"] == "sell":
                group[f"de_{side}_sell"].append(1)
            if row["action"] == "buy" and max_buy >= 2:
                group[f"ad_{side}"].append((quantity - 1) / (max_buy - 1))
        period = "surge" if row["date"] in surge else "normal"
        group[f"{period}_{row['action']}_value"].append(quantity * price)
        group[f"{period}_op"].append(1)
    result = {}
    for agent in [f"A{i:03d}" for i in range(1, 101)]:
        group = groups[agent]
        ad_loss = group["ad_loss"]
        ad_gain = group["ad_gain"]
        ad = sum(ad_loss) / len(ad_loss) - sum(ad_gain) / len(ad_gain) if ad_loss and ad_gain else None
        de_loss_op = len(group["de_loss_op"])
        de_gain_op = len(group["de_gain_op"])
        de_loss_sell = len(group["de_loss_sell"])
        de_gain_sell = len(group["de_gain_sell"])
        de = (
            de_gain_sell / de_gain_op - de_loss_sell / de_loss_op
            if de_gain_op and de_loss_op else None
        )
        surge_buy = sum(group["surge_buy_value"])
        surge_sell = sum(group["surge_sell_value"])
        normal_buy = sum(group["normal_buy_value"])
        normal_sell = sum(group["normal_sell_value"])
        surge_vbsi = vbsi(surge_buy, surge_sell)
        normal_vbsi = vbsi(normal_buy, normal_sell)
        excess = surge_vbsi - normal_vbsi if surge_vbsi is not None and normal_vbsi is not None else None
        result[agent] = {
            "ad": ad,
            "de": de,
            "surge_vbsi": surge_vbsi,
            "normal_vbsi": normal_vbsi,
            "excess": excess,
            "ad_flag": ad is not None and ad > EPS,
            "de_flag": de is not None and de > EPS,
            "surge_flag": surge_vbsi is not None and excess is not None and surge_vbsi > EPS and excess > EPS,
            "ad_loss_buys": len(ad_loss),
            "ad_gain_buys": len(ad_gain),
            "de_loss_op": de_loss_op,
            "de_gain_op": de_gain_op,
            "de_loss_sell": de_loss_sell,
            "de_gain_sell": de_gain_sell,
            "surge_op": len(group["surge_op"]),
            "surge_buy_value": surge_buy,
            "surge_sell_value": surge_sell,
            "normal_buy_value": normal_buy,
            "normal_sell_value": normal_sell,
        }
    return result


def check_parent(parent: dict[str, dict]) -> dict:
    expected = {}
    for line in REPORT.read_text(encoding="utf-8-sig").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) == 7 and cells[1].startswith("A") and cells[1][1:].isdigit():
            try:
                expected[cells[1]] = [float(value) for value in cells[2:6]]
            except ValueError:
                pass
    assert len(expected) == 100, len(expected)
    maximum_error = 0.0
    for agent, scores in expected.items():
        observed = parent[agent]
        for expected_score, observed_score in zip(scores, (observed["ad"], observed["de"], observed["surge_vbsi"], observed["excess"])):
            assert observed_score is not None, agent
            maximum_error = max(maximum_error, abs(expected_score - observed_score))
            assert abs(expected_score - observed_score) < 1e-5, (agent, expected_score, observed_score)
    counts = {
        flag: sum(row[flag] for row in parent.values())
        for flag in ("ad_flag", "de_flag", "surge_flag")
    }
    assert counts == {"ad_flag": 60, "de_flag": 86, "surge_flag": 36}, counts
    return {"agents": len(expected), "maximum_score_error_from_rounded_report": maximum_error, "flags": counts}


def aggregate(results: dict[str, dict[str, dict]]) -> dict:
    flags = ("ad_flag", "de_flag", "surge_flag")
    parent = results["parent"]
    post = ("off", "general", "personal")
    summary = {
        "flag_counts": {name: {flag: sum(row[flag] for row in scores.values()) for flag in flags} for name, scores in results.items()},
        "initially_any": sum(any(row[flag] for flag in flags) for row in parent.values()),
        "by_agent": {},
    }
    for agent in parent:
        diagnosed = [flag for flag in flags if parent[agent][flag]]
        record = {
            "initial_diagnosed": diagnosed,
            "scores": {name: results[name][agent] for name in results},
            "cleared": {
                name: [flag for flag in diagnosed if not results[name][agent][flag]]
                for name in post
            },
        }
        record["no_clearance_any_arm"] = bool(diagnosed) and all(not record["cleared"][name] for name in post)
        record["no_clearance_either_advice"] = bool(diagnosed) and not record["cleared"]["general"] and not record["cleared"]["personal"]
        summary["by_agent"][agent] = record
    summary["no_clearance_any_arm"] = [agent for agent, item in summary["by_agent"].items() if item["no_clearance_any_arm"]]
    summary["no_clearance_either_advice"] = [agent for agent, item in summary["by_agent"].items() if item["no_clearance_either_advice"]]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", action="append", help="Print full score/denominator details for an agent")
    args = parser.parse_args()
    surge = surge_dates()
    parent_states = load_states("parent")
    results = {name: score_run(name, parent_states, surge) for name in NAMES}
    summary = aggregate(results)
    print("PARENT_CHECK", json.dumps(check_parent(results["parent"]), ensure_ascii=False))
    print("SURGE_DATES", json.dumps({
        name: sorted(d for d in surge if ("2026-02-27" <= d <= "2026-05-04") if name == "parent")
        if name == "parent" else sorted(d for d in surge if "2026-05-06" <= d <= "2026-07-09")
        for name in ("parent", "post")
    }))
    print("SUMMARY", json.dumps({k: v for k, v in summary.items() if k != "by_agent"}, ensure_ascii=False))
    for agent in args.agent or []:
        print("AGENT", agent, json.dumps(summary["by_agent"][agent], ensure_ascii=False))


if __name__ == "__main__":
    main()
