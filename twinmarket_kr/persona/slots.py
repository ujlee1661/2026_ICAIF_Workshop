from __future__ import annotations

import csv
from pathlib import Path

import config


SLOT_ROWS = """
A001,여성,21,20대,1억
A002,여성,22,20대,1억
A003,남성,23,20대,1억
A004,남성,24,20대,1억
A005,여성,25,20대,1억
A006,남성,26,20대,1억
A007,여성,27,20대,1억
A008,여성,28,20대,1억
A009,남성,29,20대,1억
A010,여성,30,30대,1억
A011,남성,31,30대,1억
A012,남성,32,30대,1억
A013,남성,33,30대,1억
A014,여성,34,30대,1억
A015,여성,35,30대,1억
A016,여성,36,30대,1억
A017,여성,37,30대,1억
A018,남성,38,30대,1억
A019,남성,39,30대,1억
A020,남성,30,30대,1억
A021,여성,31,30대,1억
A022,여성,32,30대,1억
A023,여성,33,30대,1억
A024,여성,34,30대,1억
A025,여성,35,30대,1억
A026,여성,36,30대,1억
A027,여성,37,30대,1억
A028,남성,40,40대,1억
A029,남성,41,40대,1억
A030,남성,42,40대,1억
A031,남성,40,40대,1억
A032,여성,41,40대,1억
A033,여성,42,40대,1억
A034,여성,40,40대,1억
A035,여성,41,40대,1억
A036,여성,42,40대,1억
A037,남성,43,40대,1억
A038,남성,44,40대,1억
A039,여성,45,40대,10억
A040,여성,46,40대,1억
A041,남성,47,40대,1억
A042,남성,48,40대,1억
A043,여성,49,40대,10억
A044,여성,43,40대,1억
A045,남성,44,40대,1억
A046,여성,45,40대,1억
A047,여성,46,40대,1억
A048,여성,47,40대,1억
A049,여성,48,40대,1억
A050,여성,49,40대,1억
A051,여성,50,50대,1억
A052,남성,51,50대,10억
A053,여성,52,50대,1억
A054,남성,53,50대,1억
A055,남성,54,50대,1억
A056,여성,55,50대,10억
A057,남성,50,50대,1억
A058,여성,51,50대,1억
A059,여성,52,50대,1억
A060,여성,53,50대,1억
A061,여성,54,50대,1억
A062,여성,55,50대,1억
A063,남성,50,50대,10억
A064,여성,51,50대,1억
A065,남성,52,50대,1억
A066,여성,53,50대,1억
A067,남성,54,50대,1억
A068,남성,55,50대,1억
A069,여성,56,50대,1억
A070,남성,57,50대,1억
A071,여성,58,50대,10억
A072,여성,59,50대,1억
A073,남성,56,50대,1억
A074,여성,57,50대,1억
A075,여성,58,50대,1억
A076,여성,59,50대,1억
A077,여성,60,60대,1억
A078,여성,61,60대,1억
A079,여성,62,60대,1억
A080,남성,63,60대,10억
A081,여성,64,60대,1억
A082,남성,65,60대,10억
A083,남성,66,60대,1억
A084,남성,60,60대,1억
A085,남성,61,60대,1억
A086,남성,62,60대,1억
A087,여성,63,60대,10억
A088,남성,64,60대,1억
A089,남성,65,60대,1억
A090,남성,66,60대,1억
A091,여성,67,60대,1억
A092,남성,68,60대,1억
A093,여성,69,60대,1억
A094,여성,70,70대,1억
A095,남성,72,70대,1억
A096,여성,74,70대,1억
A097,남성,76,70대,10억
A098,남성,78,70대,1억
A099,여성,79,70대,1억
A100,남성,82,80대 이상,1억
""".strip()


def parse_gender(value: str) -> str:
    return "male" if value.strip() == "남성" else "female"


def parse_cash(value: str) -> int:
    value = value.strip()
    if value == "1억":
        return config.INI_CASH_SMALL
    if value == "10억":
        return config.INI_CASH_LARGE
    return int(value.replace(",", ""))


def default_slots() -> list[dict]:
    rows: list[dict] = []
    for line in SLOT_ROWS.splitlines():
        agent_id, gender, age, age_group, cash = [part.strip() for part in line.split(",")]
        rows.append(
            {
                "agent_id": agent_id,
                "gender": parse_gender(gender),
                "age": int(age),
                "age_group": age_group,
                "ini_cash": parse_cash(cash),
            }
        )
    return rows


def write_default_fixed_slots(path: Path = config.FIXED_SLOTS_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["agent_id", "성별", "나이", "연령대", "운용자산"])
        for line in SLOT_ROWS.splitlines():
            writer.writerow([part.strip() for part in line.split(",")])


def load_fixed_slots(path: Path = config.FIXED_SLOTS_CSV) -> list[dict]:
    if not path.exists():
        write_default_fixed_slots(path)
    slots: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slots.append(
                {
                    "agent_id": row["agent_id"],
                    "gender": parse_gender(row["성별"]),
                    "age": int(row["나이"]),
                    "age_group": row["연령대"],
                    "ini_cash": parse_cash(row["운용자산"]),
                }
            )
    if len(slots) != 100:
        raise ValueError(f"fixed slot count must be 100, got {len(slots)}")
    return slots
