from __future__ import annotations

import config


SEGMENT_PROFILES = {
    "male_20대_일반": {
        "bh_lottery_preference_category": ["high", "medium"],
        "strategy": ["technical"],
        "bh_disposition_effect_category": ["high", "medium"],
    },
    "female_20대_일반": {
        "bh_lottery_preference_category": ["low", "medium"],
        "strategy": ["technical", "value"],
        "bh_disposition_effect_category": ["medium", "low"],
    },
    "male_30대_일반": {
        "bh_lottery_preference_category": ["high", "medium"],
        "strategy": ["technical"],
        "bh_disposition_effect_category": ["high", "medium"],
    },
    "female_30대_일반": {
        "bh_lottery_preference_category": ["low", "medium"],
        "strategy": ["value", "technical"],
        "bh_disposition_effect_category": ["medium", "low"],
    },
    "male_40대_일반": {
        "bh_lottery_preference_category": ["medium", "high"],
        "strategy": ["technical"],
        "bh_disposition_effect_category": ["medium", "high"],
    },
    "male_40대_고액": {
        "bh_lottery_preference_category": ["medium", "low"],
        "strategy": ["technical", "value"],
        "bh_disposition_effect_category": ["medium"],
    },
    "female_40대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value", "technical"],
        "bh_disposition_effect_category": ["low", "medium"],
    },
    "female_40대_고액": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "male_50대_일반": {
        "bh_lottery_preference_category": ["medium"],
        "strategy": ["technical"],
        "bh_disposition_effect_category": ["high", "medium"],
    },
    "male_50대_고액": {
        "bh_lottery_preference_category": ["low", "medium"],
        "strategy": ["technical", "value"],
        "bh_disposition_effect_category": ["medium"],
    },
    "female_50대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low", "medium"],
    },
    "female_50대_고액": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "male_60대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value", "technical"],
        "bh_disposition_effect_category": ["medium", "low"],
    },
    "male_60대_고액": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["medium"],
    },
    "female_60대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "female_60대_고액": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "male_70대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low", "medium"],
    },
    "male_70대_고액": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "female_70대_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
    "male_80대 이상_일반": {
        "bh_lottery_preference_category": ["low"],
        "strategy": ["value"],
        "bh_disposition_effect_category": ["low"],
    },
}


def segment_key(age_group: str, gender: str, ini_cash: int) -> str:
    asset_group = "고액" if ini_cash >= config.INI_CASH_LARGE else "일반"
    return f"{gender}_{age_group}_{asset_group}"


def get_behavioral_profile(age_group: str, gender: str, ini_cash: int) -> dict[str, list[str]]:
    key = segment_key(age_group, gender, ini_cash)
    return SEGMENT_PROFILES.get(key, SEGMENT_PROFILES["male_60대_일반"])
