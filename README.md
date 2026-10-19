# TwinMarket Korea

삼성전자 실제 가격을 외생적으로 고정한 개인투자자 에이전트 시뮬레이션입니다.
실제뉴스와 커뮤니티 노출에 따른 거래 행동을 비교하고, 동일한 사전 상태에서
일반·개인화 Advisor 조언의 효과를 비교합니다.

논문: [Can Personalized Advice Improve Investor Behavior? Evidence from a Multi-Agent Simulation of Retail Investors](outputs/Can%20Personalized%20Advice%20Improve%20Investor%20Behavior%3F.pdf)

> 문서 확인일: 2026-10-19. 현재 코드, 봉인 입력, 보존된 실행 메타데이터를
> 기준으로 작성했습니다. 입력 profile의 전체 기간과 개별 run의 완료 범위는
> 서로 다르므로, 결과는 각 run의 완료·검증 기록과 함께 확인합니다.

## 실행 구조

기본 실험 엔진은 다음 한 경로입니다. Community와 Advisor 설정도 같은
엔진에 적용하며, 별도의 RN 전용 runner를 사용하지 않습니다.

```text
scripts/00_fetch_market_data.py       시장 데이터 준비
scripts/01_build_persona.py           persona 준비
scripts/02_prepare_news.py            봉인 뉴스 검증
scripts/03_load_stock_data.py         가격 검증 / 명시적 CSV 적재
scripts/04_build_experiment_base.py   turn-zero DB 생성
scripts/05_run_simulation.py
  -> twinmarket_kr/simulation.py
     -> core / agents / community / advisor
     -> canonical DB + event journal + CSV/JSONL
     -> scripts/99_validate.py + 보고서
```

배포된 baseline을 사용할 때는 봉인 cohort·뉴스를 그대로 사용합니다.
`00`·`01`은 입력을 새로 준비하는 단계이므로 빠른 시작에서 다시 실행하지 않습니다.
`08_run_six_conditions.py`는 같은 `05` 실행기를 조건별로 호출하는 orchestration
스크립트이며, 기본 비교는 `RN_COMM_OFF`와 `RN_COMM_ON`입니다.

한 event의 실행 순서는 다음과 같습니다.

```text
도래한 과거 성과와 AM 커뮤니티 노출 확정
  -> 현재 STB 6차원
  -> 이전 LTB + 현재 STB로 분석과 거래 의도(decision) 생성
  -> 잔고·보유량 제약을 반영한 실제 체결(fill)
  -> post-fill LTB 6차원
  -> PM 커뮤니티
```

STB/LTB, decision/fill 계보와 event journal을 보존합니다. H1/H5 성과는 해당
결과가 도래한 뒤에만 반영하며, `belief_summary`는 사람용 파생 로그입니다.

## 기본 입력과 실험 설정

현재 코드의 기본 profile은
[`preparation/rn_ab_sealed_to_20260722_v1/`](preparation/rn_ab_sealed_to_20260722_v1/)입니다.
정책과 입력 hash는 이 폴더의 `study_spec.json` 및 registry에서 확인합니다.

| 항목 | 기본값 |
| --- | --- |
| 종목 | 삼성전자, `005930` |
| 입력 기간 | 2026-02-27 ~ 2026-07-22, 98거래일·196 events |
| cohort | `data/sys_100_ko_ver5.db`, 100명, D0/D1/D2 = 30/55/15 |
| 실제뉴스 | 1,602 slots, 제목·요약만 사용 |
| 뉴스 선정 목표 | event별 종목 5 / 산업 3 / 거시 2, 부족분은 다른 category로 채우지 않음 |
| 거래 | 수수료 0, 매수·매도 결정, 실제 체결은 잔고·보유량 제약 적용 |
| 분석 burn-in | 첫 3거래일 |
| 모델 / provider | `qwen/qwen3.5-flash-02-23` / `alibaba`, fallback 금지 |
| reasoning | `effort=none`, `exclude=true` |
| 기본 base DB | `outputs/experiment_base_to_20260722.db` |

| profile 파일 | 역할 |
| --- | --- |
| `study_spec.json` | 실험·모델·거래·기억 정책과 입력·prompt hash |
| `cohort.json` | agent ID와 depth |
| `news.json` | event별 실제뉴스와 shortage 기록 |
| `calendar.json` | 거래일과 AM/PM event |
| `prices.json` | event별 체결 가격 |
| `stage_inputs.json` | 단계별 봉인 입력 |

현재 뉴스 hash는 다음과 같습니다.

```text
bundle  6ba52298c4d00029ee370c5f6d5d43d4860658e8c27dd9ed66482ee4f40dc11c
file    b45a1b71d25e8cf4738a63a921dad313eb5445503b286b176820d8ee5b3da197
```

D0는 뉴스 제목만, D1은 제목과 요약을 받습니다. D2는 여기에 최근 7일의
cutoff-safe 검색 요약 최대 5건을 추가로 받습니다. 기사 본문은 노출하지 않습니다.

`rn_ab_sealed_v1/`과 `rn_ab_sealed_to_20260529_v1/` 등은 다른 기간의
보존 profile입니다. 각 run이 실제 사용한 입력은 `run_signature.json`과
`run_metadata.json`으로 확인합니다. 신규 baseline은 과거 결과에서 뉴스를
재샘플링하지 않습니다. fake 조건은 대응하는 별도 봉인 profile이 필요합니다.

## 설치와 무과금 빠른 시작

Python 3.12와 Git LFS를 준비합니다. GitHub에서 clone한 뒤 저장소 루트에서
다음을 실행합니다. 대용량 파일은 Git LFS 객체까지 내려받아야 합니다.

```bash
git lfs install
git lfs pull
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export TWINMARKET_OFFLINE_LLM=1
```

`.env`와 `.venv/`는 배포되지 않습니다. 코드가 offline을 기본으로 선택하지
않으므로 무과금 실행에는 위 환경변수를 명시합니다. offline stub은 실행 흐름과
artifact 검증용이며 실제 모델의 선택률이나 투자 성과를 측정하지 않습니다.

봉인 뉴스와 가격을 검증하고, 빠른 시작 전용 DB를 만듭니다. 아래 `03` 명령은
배포된 `data/stock_data.csv`를 별도 DB에 적재하는 명시적 쓰기 작업입니다.

```bash
python scripts/02_prepare_news.py
python scripts/03_load_stock_data.py \
  --write \
  --source data/stock_data.csv \
  --target outputs/local_market_data.db \
  --profile-root preparation/rn_ab_sealed_to_20260722_v1
python scripts/04_build_experiment_base.py \
  --source outputs/local_market_data.db \
  --output outputs/local_experiment_base.db \
  --profile-root preparation/rn_ab_sealed_to_20260722_v1
```

`03`에서 `--write`를 빼면 읽기 전용 가격 검증입니다. `04`는 기존 output이
있으면 중단하므로 이미 만든 DB를 쓸 때는 다시 생성하지 않아도 됩니다.
재생성이 필요할 때만 대상 경로를 확인하고 `--force`를 사용합니다.

현재 cohort는 첫 D2가 `A022`이므로 다음 smoke는 23명을 사용합니다.
Community ON의 게시·선택·반응을 포함해 1거래일을 실행합니다.

```bash
TWINMARKET_OFFLINE_LLM=1 python scripts/05_run_simulation.py \
  --base-db outputs/local_experiment_base.db \
  --max-agents 23 \
  --max-days 1 \
  --community-mode on \
  --run-dir outputs/logs/local_offline_smoke
```

중단 후 재개할 때는 같은 명령과 같은 경로에 `--resume`만 추가합니다.
입력·seed·조건을 바꾸면 서명 검증에서 거부됩니다. `--max-agents`는 offline
smoke용이며 유료 실험의 cohort 변경에는 별도 봉인이 필요합니다.

전체 무과금 회귀 테스트는 다음 명령으로 실행합니다. 이 문서 갱신 과정에서는
전체 테스트나 E2E를 새로 실행하지 않았습니다.

```bash
TWINMARKET_OFFLINE_LLM=1 python -m pytest -q
```

## Community OFF/ON 비교

두 조건의 1거래일 offline 비교 예시입니다. 각 조건은 전체 cohort를 사용합니다.
전체 입력 기간을 검사하려면 시작·종료일 옵션을 생략합니다.

```bash
TWINMARKET_OFFLINE_LLM=1 python scripts/08_run_six_conditions.py \
  --conditions RN_COMM_OFF RN_COMM_ON \
  --start-date 2026-02-27 \
  --end-date 2026-02-27 \
  --experiment-base-db outputs/local_experiment_base.db \
  --real-profile-root preparation/rn_ab_sealed_to_20260722_v1 \
  --output-root outputs/logs/local_offline_pair
```

현재 커뮤니티 정책은 D1/D2의 자율 게시(최대 1개), 선택 읽기 각 최대 5개,
본문 최대 500자입니다. D0는 게시·선택 읽기를 하지 않지만 다음 AM Best를
받습니다. 동결된 제목 후보는 `title_only`, 실제 읽은 본문은 `full_body`로
구분하며, 반응은 `like`·`unlike`·`none`입니다. Best는 기존 반응 점수로 전역
최대 5개를 정한 뒤 작성자 자신에게는 전달하지 않고 다음 순위로 보충하지
않습니다. 상세 규칙은 [실험 설계](EXPERIMENT_DESIGN.md)에서 관리합니다.

## Advisor 비교

Advisor도 `05_run_simulation.py`에서 실행합니다. 기본은
`--advisor-mode off`이며, ON에는 `--advisor-mode on`과
`--advisor-artifact <messages.json>`이 함께 필요합니다. 현재 CLI는 유효 시점
이후 매 event에 고정 조언을 재노출하는 정책입니다. 보존된 과거 run의 노출
정책은 당시 signature와 artifact를 확인합니다.

`--warm-base --parent-run-dir <parent-run>`은 검증된 2026-05-04 PM 종료
상태를 이어받습니다. `--base-db`에는 해당 parent의 검증된 canonical DB를
지정해야 합니다. `16_prepare_advisor_inputs.py`는 과거 상태 기반 입력을 만들고,
`17_generate_advisor_artifact.py`는 명시적 유료 승인 아래 조언을 생성합니다.

5월 29일 종료 설계와 7월 확장 실행은 구분합니다. 연구 계약, 조언 생성과
warm-fork 절차는 [advisor_plan.md](advisor_plan.md)를 따릅니다.

## 보존 결과의 시작점

최근 Advisor 결과는 [`outputs/experiments/`](outputs/experiments/)에 있습니다.
폴더명의 종료일만으로 완료 여부를 판단하지 않습니다.

| run 폴더 | 보존 상태 |
| --- | --- |
| `ADVISOR_MAIN_FROM_SCRATCH_PARENT_20260923` | 2026-05-04 PM까지 90 events, `segment_complete` |
| `ADVISOR_GENERAL_20261001_TO_20260710` | 2026-07-10 PM까지 92 continuation events, segment 검증 기록 있음 |
| `ADVISOR_PERSONAL_20261001_TO_20260710` | 2026-07-10 PM까지 92 continuation events, segment 검증 기록 있음 |
| `ADVISOR_MAIN_CONT_OFF_20260925` | checkpoint 92 events, 최종 완료 marker 없음 |
| `ADVISOR_GENERAL_REPEAT_20261002_TO_20260710` | 별도 closure가 인정한 분석 범위는 2026-07-06 PM까지 84 events |
| `ADVISOR_PERSONALIZED_V5_20261003_TO_20260710` | metadata/checkpoint 89 events·2026-07-09 AM, 완료 marker 없음 |

General·Personal의 저장된 검증 상태는 `segment_valid_not_publication_ready`입니다.
검증 JSON은 [`outputs/validation/`](outputs/validation/)에 있습니다. Repeat의
원본 checkpoint와 인정 범위는 다르며, 범위 정의는
[closure JSON](outputs/experiments/derived/ADVISOR_GENERAL_REPEAT_20261002_TO_20260706PM_closure.json)을
확인합니다. V5의 별도 AM cutoff 분석은
[cutoff 문서](outputs/experiments/derived/ADVISOR_PERSONALIZED_V5_ASOF_20260708_AM/README.md)와
해당 manifest의 범위를 따릅니다. 이들 부분 결과를 전체 기간 완료로 집계하지 않습니다.

공통 구간 분석과 cutoff 파생물은
[`outputs/experiments/derived/`](outputs/experiments/derived/)에 있습니다.
대용량 runtime·로그 일부는 분할 압축 또는 Git LFS로 보관합니다. 복원 가능한
run과 checksum 확인 방법은
[archive 복원 안내](outputs/experiments/advisor_runtime_archives_20261002/README.md)를
확인합니다. GitHub의 CSV 목록만으로 `.runtime/`까지 복원되었다고 가정하지 않습니다.

기존 Community OFF/ON 자료는 `outputs/logs/rn_ab_ver6_45day_20260826/`에
있습니다. [`outputs/PRIMARY_RUNS.md`](outputs/PRIMARY_RUNS.md)는 과거 Community
결과 안내이며 최신 Advisor 실행 목록을 대신하지 않습니다. 그 문서에 기록된
`outputs/experiments/RN_COMM_ON_20260918/`은 현재 작업 트리에 없습니다.
과거 로그·archive는 분석 보존 자료이며 신규 baseline 입력으로 쓰지 않습니다.

## 검증과 보고서

run을 지정해 검증하고 파생물은 run 디렉터리 밖에 생성합니다. 아래는
`local_offline_smoke`의 기간 제한 실행을 검사하는 예시입니다.

```bash
python scripts/99_validate.py \
  --run-dir outputs/logs/local_offline_smoke \
  --allow-segment \
  --output outputs/local_offline_smoke_validation.json
```

`--allow-segment`는 부분 기간의 무결성 검사용이며 publication-ready 판정이
아닙니다. 전체 완료 run은 이 옵션 없이 검사합니다. 방향성 검증과 PDF 보고서의
실행 인자는 다음 명령으로 확인하며, 실제 생성은 run의 검증 gate를 따라야 합니다.

```bash
python validation/validate_trading_direction.py --help
python scripts/generate_run_report_pdf.py --help
python scripts/generate_community_report_pdf.py --help
```

| 확인 목적 | run 내부 artifact |
| --- | --- |
| 실행 조건·서명 | `run_metadata.json`, `run_signature.json` |
| 전체 / 구간 완료 | `run_complete.json` / `segment_complete.json` |
| 커밋·재개 상태 | `.runtime/checkpoint.json` |
| 정본 DB | `.runtime/committed.db` |
| 실제 체결 / 거래 의도 | `exchange_fills.csv` / `submitted_orders.csv` |
| STB/LTB 계보 | `memory_lineage.jsonl`, `agent_turns.jsonl` |
| 커뮤니티 게시·노출·Best | `community_posts.csv`, `community_interactions.csv`, `community_best_posts.csv` |

유료 실행 전에는 **전체 테스트 → D2를 포함한 offline E2E → 유료 검증** 순서를
지킵니다. 현재 코드·prompt·입력에 맞는 봉인과 preflight, 명시적 비용 승인,
reasoning-off canary audit가 필요합니다. live 실행에는 `--allow-paid-api`와
`--reasoning-off-canary-audit`를 함께 지정합니다. 절차는
[RUNBOOK_AND_PREFLIGHT.md](RUNBOOK_AND_PREFLIGHT.md)를 따릅니다.

## 문서와 디렉터리

| 경로 | 역할 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 공통 엔진, 기억·거래·커뮤니티, artifact 구조 |
| [EXPERIMENT_DESIGN.md](EXPERIMENT_DESIGN.md) | 연구 질문, 조건, 정책과 지표 |
| [RUNBOOK_AND_PREFLIGHT.md](RUNBOOK_AND_PREFLIGHT.md) | prepare, preflight, run, resume, validate, report |
| [advisor_plan.md](advisor_plan.md) | Advisor 연구 계약과 fork 절차 |
| `prompts/` | production prompt 정본 |
| `analysis/`, `validation/` | 분석 코드와 결과 검증 도구 |
| `archive/` | 과거 입력·결과와 필요한 provenance 자료 |

`AGENTS.md`는 작업 지침입니다. 역사 문서와 결과 sidecar의 수치·실행 예시는
현재 CLI 및 각 run의 봉인 계약과 대조해서 사용합니다. 논문 작성 자료,
생성된 이미지, 오래된 개발 계획·인수인계 메모는 배포에서 정리했으며,
추적되었던 삭제 파일은 Git history에서 확인할 수 있습니다.
