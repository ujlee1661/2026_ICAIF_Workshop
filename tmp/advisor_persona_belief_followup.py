"""Read-only exploratory comparison of persona, belief wording, and DE response."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advisor_original_criteria_analysis as audit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPERIMENTS = ROOT / "outputs/experiments"
TARGETS = ("A037", "A084", "A093")
RNG = np.random.default_rng(20261005)


def db_rows(path: Path, query: str) -> list[dict]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [dict(item) for item in connection.execute(query)]
    connection.close()
    return rows


def belief_rows(arm: str, turn: int) -> dict[str, dict]:
    path = EXPERIMENTS / audit.NAMES[arm] / ".runtime/runtime_sim.db"
    query = (
        "select agent_id,turn,dim_1,dim_2,dim_3,dim_4,dim_5,dim_6 "
        f"from simulation_ltb_states where turn={turn}"
    )
    rows = db_rows(path, query)
    assert len(rows) == 100
    return {row["agent_id"]: row for row in rows}


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(x, y)[0, 1])


def permutation_p(x: np.ndarray, y: np.ndarray, observed: float, n: int = 20000) -> float:
    count = 0
    for _ in range(n):
        if abs(pearson(x, RNG.permutation(y))) >= abs(observed):
            count += 1
    return (count + 1) / (n + 1)


def bootstrap_corr_ci(x: np.ndarray, y: np.ndarray, n: int = 20000) -> list[float]:
    values = []
    for _ in range(n):
        index = RNG.integers(0, len(x), len(x))
        if len(np.unique(x[index])) > 1 and np.std(y[index]) > 0:
            values.append(pearson(x[index], y[index]))
    return [float(v) for v in np.percentile(values, [2.5, 97.5])]


def summarize(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean_pp": round(float(np.mean(values)) * 100, 3),
        "median_pp": round(float(np.median(values)) * 100, 3),
    }


def ols_hc3(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    coefficients = np.linalg.lstsq(x, y, rcond=None)[0]
    residuals = y - x @ coefficients
    inverse = np.linalg.inv(x.T @ x)
    h = np.sum((x @ inverse) * x, axis=1)
    adjusted = (residuals / (1 - h)) ** 2
    covariance = inverse @ (x.T @ (x * adjusted[:, None])) @ inverse
    return coefficients, np.sqrt(np.diag(covariance))


def main() -> None:
    surge = audit.surge_dates()
    parent_states = audit.load_states("parent")
    scores = {arm: audit.score_run(arm, parent_states, surge) for arm in audit.NAMES}
    audit.check_parent(scores["parent"])
    persona_rows = db_rows(ROOT / "data/sys_100_ko_ver5.db", "select * from agents")
    personas = {row["agent_id"]: row for row in persona_rows}
    ids = sorted(personas)
    assert len(ids) == 100
    projection = json.loads((ROOT / "preparation/rn_ab_sealed_v1/persona_projection.json").read_text())
    assert projection["source_db_sha256"] == hashlib.sha256(
        (ROOT / "data/sys_100_ko_ver5.db").read_bytes()
    ).hexdigest()
    from twinmarket_kr.persona.select import generate_persona_prompt, structured_persona_sha256
    by_id = {row["agent_id"]: row for row in projection["agents"]}
    for agent in ids:
        assert structured_persona_sha256(personas[agent]) == by_id[agent]["structured_persona_sha256"]
        assert hashlib.sha256(generate_persona_prompt(personas[agent], instrument_name="삼성전자").encode()).hexdigest() == by_id[agent]["persona_sha256"]

    print("INITIAL_FLAGS", json.dumps({agent: {
        "ad": scores["parent"][agent]["ad_flag"],
        "de": scores["parent"][agent]["de_flag"],
        "surge": scores["parent"][agent]["surge_flag"],
    } for agent in TARGETS}, ensure_ascii=False))

    categories = {"low": 0.0, "medium": 1.0, "high": 2.0}
    x = np.array([categories[personas[agent]["bh_disposition_effect_category"]] for agent in ids])
    for arm in ("parent", "off"):
        y = np.array([scores[arm][agent]["de"] for agent in ids])
        observed = pearson(x, y)
        print("PERSONA_ASSOC", arm, json.dumps({
            "r_ordinal_pearson": round(observed, 5),
            "permutation_p_two_sided": round(permutation_p(x, y, observed), 5),
            "bootstrap_95pct_ci": [round(v, 5) for v in bootstrap_corr_ci(x, y)],
            "groups": {category: {
                **summarize([scores[arm][agent]["de"] for agent in ids if personas[agent]["bh_disposition_effect_category"] == category]),
                "positive": sum(scores[arm][agent]["de_flag"] for agent in ids if personas[agent]["bh_disposition_effect_category"] == category),
            } for category in categories},
        }, ensure_ascii=False))

    initial_de = [agent for agent in ids if scores["parent"][agent]["de_flag"]]
    de_only = [agent for agent in initial_de if not scores["parent"][agent]["ad_flag"] and not scores["parent"][agent]["surge_flag"]]
    print("BASE_RATES", json.dumps({
        "initial_de": len(initial_de),
        "de_only": len(de_only),
        "d1_all": sum(personas[agent]["news_depth"] == 1 for agent in ids),
        "d1_de_only": sum(personas[agent]["news_depth"] == 1 for agent in de_only),
        "male_all": sum(personas[agent]["gender"] == "남성" for agent in ids),
        "male_de_only": sum(personas[agent]["gender"] == "남성" for agent in de_only),
    }, ensure_ascii=False))

    parent_beliefs = belief_rows("parent", 90)
    followup_beliefs = belief_rows("personal", 91)
    term = re.compile(r"매도(?:는| 후).{0,35}(?:상승|올랐|오름)")
    mentioned = {agent: bool(term.search(parent_beliefs[agent]["dim_6"])) for agent in ids}
    print("BELIEF_BASE_RATE", json.dumps({
        "pattern": term.pattern,
        "all": sum(mentioned.values()),
        "de_only": sum(mentioned[agent] for agent in de_only),
        "targets": {agent: mentioned[agent] for agent in TARGETS},
    }, ensure_ascii=False))

    explicit = {agent: any(term in followup_beliefs[agent]["dim_6"] for term in ("어드바이저", "조언", "처분효과")) for agent in ids}
    print("REFLECTION_BASE_RATE", json.dumps({
        "all": sum(explicit.values()),
        "initial_de": sum(explicit[agent] for agent in initial_de),
        "targets": {agent: explicit[agent] for agent in TARGETS},
        "strict_advisor_or_advice": sum(any(term in followup_beliefs[agent]["dim_6"] for term in ("어드바이저", "조언")) for agent in ids),
    }, ensure_ascii=False))

    for population_name, population in (("all", ids), ("initial_de", initial_de), ("de_only", de_only)):
        result = {}
        for flag in (False, True):
            group = [agent for agent in population if explicit[agent] == flag]
            change = [scores["personal"][agent]["de"] - scores["off"][agent]["de"] for agent in group]
            result[str(flag)] = {
                **summarize(change),
                "improved": sum(value < -audit.EPS for value in change),
                "worsened_or_equal": sum(value >= -audit.EPS for value in change),
            }
        print("REFLECTION_VS_CHANGE", population_name, json.dumps(result, ensure_ascii=False))

    strict_reflection = {
        agent: any(term in followup_beliefs[agent]["dim_6"] for term in ("어드바이저", "조언"))
        for agent in ids
    }
    for population_name, population in (("all", ids), ("initial_de", initial_de)):
        result = {}
        for flag in (False, True):
            group = [agent for agent in population if strict_reflection[agent] == flag]
            change = [scores["personal"][agent]["de"] - scores["off"][agent]["de"] for agent in group]
            result[str(flag)] = {
                **summarize(change),
                "improved": sum(value < -audit.EPS for value in change),
            }
        print("STRICT_REFLECTION_VS_CHANGE", population_name, json.dumps(result, ensure_ascii=False))

    # Descriptive adjusted association; reflection is post-treatment, not a causal covariate.
    for population_name, population in (("all", ids), ("initial_de", initial_de)):
        y = np.array([(scores["personal"][agent]["de"] - scores["off"][agent]["de"]) * 100 for agent in population])
        columns = [
            np.ones(len(population)),
            np.array([int(explicit[agent]) for agent in population]),
            np.array([int(personas[agent]["bh_disposition_effect_category"] == "medium") for agent in population]),
            np.array([int(personas[agent]["bh_disposition_effect_category"] == "high") for agent in population]),
            np.array([int(personas[agent]["news_depth"] == 1) for agent in population]),
            np.array([int(personas[agent]["news_depth"] == 2) for agent in population]),
            np.array([scores["parent"][agent]["de"] * 100 for agent in population]),
        ]
        names = ("intercept", "explicit_reflection", "persona_medium", "persona_high", "depth1", "depth2", "initial_de_pp")
        coefficients, standard_errors = ols_hc3(y, np.column_stack(columns))
        print("ADJUSTED_OLS", population_name, json.dumps({name: {"coef_pp": round(float(coef), 4), "hc3_se": round(float(se), 4)} for name, coef, se in zip(names, coefficients, standard_errors)}, ensure_ascii=False))

    depth_results = {}
    for depth in (0, 1, 2):
        group = [agent for agent in de_only if personas[agent]["news_depth"] == depth]
        depth_results[str(depth)] = {
            "n": len(group),
            "both_improved": sum(
                scores["general"][agent]["de"] < scores["off"][agent]["de"] - audit.EPS
                and scores["personal"][agent]["de"] < scores["off"][agent]["de"] - audit.EPS
                for agent in group
            ),
            "personal_improved": sum(scores["personal"][agent]["de"] < scores["off"][agent]["de"] - audit.EPS for agent in group),
            "general_improved": sum(scores["general"][agent]["de"] < scores["off"][agent]["de"] - audit.EPS for agent in group),
            "agents": group,
        }
    print("DE_ONLY_BY_DEPTH", json.dumps(depth_results, ensure_ascii=False))

    # Without replacement, compare D1/DE-only personal responders with at
    # least a five-point reduction. Minimize the sum of absolute differences
    # in parent and no-advice DE; the threshold and match are descriptive only.
    candidates = [agent for agent in de_only if personas[agent]["news_depth"] == 1 and scores["personal"][agent]["de"] <= scores["off"][agent]["de"] - 0.05]
    remaining = set(candidates)
    controls = {}
    for target in TARGETS:
        candidate = min(
            remaining,
            key=lambda agent: abs(scores["parent"][agent]["de"] - scores["parent"][target]["de"])
            + abs(scores["off"][agent]["de"] - scores["off"][target]["de"]),
        )
        controls[target] = candidate
        remaining.remove(candidate)
    print("MATCHED_PERSONAL_RESPONDERS", json.dumps({target: {
        "control": control,
        "target_parent_de_pp": round(scores["parent"][target]["de"] * 100, 2),
        "control_parent_de_pp": round(scores["parent"][control]["de"] * 100, 2),
        "control_off_de_pp": round(scores["off"][control]["de"] * 100, 2),
        "control_personal_de_pp": round(scores["personal"][control]["de"] * 100, 2),
        "target_t90_sell_rise_mention": mentioned[target],
        "control_t90_sell_rise_mention": mentioned[control],
        "target_t91_explicit_reflection": explicit[target],
        "control_t91_explicit_reflection": explicit[control],
    } for target, control in controls.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
