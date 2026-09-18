# BUP CSE Fest 2026 Hackathon — GridWise Execution Blueprint & Phases

> **Challenge:** Smart Campus Energy Optimization Challenge (LLM-Assisted Operator Directive Interpretation)  
> **Event Window:** 4 Hours (7:00 PM – 11:00 PM)  
> **Target:** 100/100 Points on Automated Evaluation + Tie-Breaker Video  

---

## 🏗️ System Architecture Overview

```
       [ Client / Judge Harness ]
                   │
         POST /optimize-energy
                   │
                   ▼
       ┌─────────────────────────┐
       │   FastAPI Web Server    │
       └───────────┬─────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌──────────────────┐ ┌───────────────────────┐
│  LLM Interpreter │ │ Deterministic         │
│ (Gemini 2.5/3.8) │─┼─► Guardrail Validator │
│ Extracts Intents │ │ Normalizes & Enforces │
└──────────────────┘ └───────────┬───────────┘
                                 │ Clean Directives
                                 ▼
                     ┌───────────────────────┐
                     │ LP Optimizer (PuLP)   │
                     │ Solves 24-Hour Plan   │
                     └───────────┬───────────┘
                                 │ Raw Solution
                                 ▼
                     ┌───────────────────────┐
                     │ Replay & Consistency  │
                     │ Independent Verifier  │
                     └───────────┬───────────┘
                                 │
                   ◄─────────────┘ Validated JSON Response
```

---

## 📋 Complete Implementation Phases

### Phase 1: Project Setup & Environment Configuration
- [x] Initialize Git repository & project structure.
- [x] Setup Python virtual environment & dependencies:
  - `fastapi`, `uvicorn[standard]`, `pydantic`
  - `google-genai`, `openai`
  - `pulp` (High-performance Linear Programming solver via CBC)
  - `pytest`, `requests`, `python-dotenv`
- [x] Setup `.env.example` (Do **not** commit actual secrets / API keys).
- [x] Establish directory structure and exact Pydantic contracts in `app/schemas.py`.
- [x] Populate full 10 sample cases test suite in `tests/sample_cases.json`.

---

### Phase 2: Deterministic LP Optimizer Engine (`app/optimizer.py`)
- [x] Formulate 24-hour Linear Programming (LP) model using `PuLP`:
  - **Decision Variables:**
    - `grid_kwh[h] >= 0`
    - `solar_used_kwh[h] >= 0`
    - `charge_kwh[h] >= 0`
    - `discharge_kwh[h] >= 0`
    - `battery_energy_after_kwh[h] >= 0`
  - **Constraints:**
    1. **Hourly Energy Balance:**  
       `grid_kwh[h] + solar_used_kwh[h] + discharge_kwh[h] == demand_kwh[h] + charge_kwh[h]`
    2. **Solar Bounds:**  
       `0 <= solar_used_kwh[h] <= effective_solar_kwh[h]` (No grid export)
    3. **Battery Transition:**  
       `battery_energy_after_kwh[0] == initial_energy_kwh + charge_kwh[0] - discharge_kwh[0]`  
       `battery_energy_after_kwh[h] == battery_energy_after_kwh[h-1] + charge_kwh[h] - discharge_kwh[h]`
    4. **Battery Energy Bounds:**  
       `effective_min_reserve[h] <= battery_energy_after_kwh[h] <= capacity_kwh`
    5. **Charge/Discharge Limits:**  
       `charge_kwh[h] <= max_charge_kwh_per_hour`  
       `discharge_kwh[h] <= max_discharge_kwh_per_hour`
    6. **End-of-Day Neutrality:**  
       `battery_energy_after_kwh[23] == initial_energy_kwh`
  - **Directive Integration:**
    - `solar_reduction`: `effective_solar[h] = original_solar[h] * factor`
    - `minimum_battery_reserve`: `effective_min_reserve[h] = max(base_min, directive_min)`
    - `no_charge_window`: `charge_kwh[h] == 0`
    - `no_discharge_window`: `discharge_kwh[h] == 0`
    - `max_grid_window`: `grid_kwh[h] <= max_grid_kwh`
  - **Objective Function:**  
    Minimize `sum(grid_kwh[h] * tariff_bdt_per_kwh[h])` for `h = 0..23`
- [x] Determine `battery_action`:
  - `charge` if `charge_kwh > 1e-4`
  - `discharge` if `discharge_kwh > 1e-4`
  - `idle` otherwise (`battery_kwh = 0`)
- [x] Verified with PyTest across all 10 sample cases (100% cost and energy balance match in 0.54s).

---

### Phase 3: Modular LLM Interpreter Layer & Deterministic Guardrails
- [x] Provider Abstraction & Isolated LLM Layer (`app/llm/`):
  - [x] `app/llm/provider.py`: Define `BaseLLMProvider` interface and implement `GeminiProvider` using the official `google-genai` SDK (`google.genai`). Configurable via `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_TIMEOUT`.
  - [x] `app/llm/prompt.py`: System prompt explicitly teaching:
    - Exactly 6 allowed directives: `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`.
    - Whole-hour 0–23 start-inclusive, end-exclusive interval convention (e.g. 12 PM–2 PM → `[12, 13]`).
    - Percentage remaining factor arithmetic ("reduce by 80%" → `factor = 0.20`, "allow only 80%" → `factor = 0.80`).
    - Distractors/unrelated notes strictly mapped to `no_op` (`applies: false`, `structured_adjustment: null`).
    - Instruction for zero math/scheduling by LLM.
  - [x] `app/llm/interpreter.py`: Batch note interpreter sending all operator notes (1 to 3) in a **single LLM call** to guarantee $p95 \le 5$s latency, preserving exact input note index order.
- [x] Deterministic Guardrail Validator (`app/guardrails.py`):
  - [x] Validates directive types against allowed enum.
  - [x] Enforces unique, ascending hours within `0..23`.
  - [x] Enforces `0.0 <= factor <= 1.0` for solar reduction.
  - [x] Enforces non-negative values for reserve & grid caps (`minimum_energy_kwh >= 0`, `max_grid_kwh >= 0`).
  - [x] Enforces `no_op` strict semantics: `applies = False` and `structured_adjustment = None`.
  - [x] Validates note count and preserves exact input note order `0..N-1`.
  - [x] Safe failure handling (malformed/timeout/provider error gracefully handled without crashing).
- [x] Unit Tests for LLM & Guardrails (`tests/test_llm_interpreter.py`):
  - [x] Test 1: Solar reduction by 80% (12 PM to 2 PM → `[12, 13]`, `factor=0.2`).
  - [x] Test 2: Battery reserve above 100 kWh (6 PM to 9 PM → `[18, 19, 20]`, `minimum_energy_kwh=100`).
  - [x] Test 3: No-charge window (2 AM to 5 AM → `[2, 3, 4]`).
  - [x] Test 4: No-discharge window (6 PM to 8 PM → `[18, 19]`).
  - [x] Test 5: Max-grid window (6 PM to 9 PM → `[18, 19, 20]`, `max_grid_kwh=155`).
  - [x] Test 6: Irrelevant meeting note → `no_op` (`applies: false`, `null`).
  - [x] Test 7: Multi-note batch preservation (`input order == output order`).
  - [x] Guardrail rejection tests: Out-of-order hours, out-of-bound factors, unknown directive types.
- [x] Verified with PyTest (12 passed in 0.25s).

---

### Phase 4: Verification & Recalculation Engine (`app/verifier.py`)
- [x] Independent replay of the generated schedule:
  - [x] Verify hourly energy balance (`grid + solar_used + discharge == demand + charge`).
  - [x] Verify battery state transition and neutrality (`E_23 == E_init`).
  - [x] Verify solar constraints, battery bounds, and rate limits.
  - [x] Verify directive constraints (`no_charge_window`, `no_discharge_window`, `min_reserve`, `max_grid`).
  - [x] Recalculate `total_grid_kwh = sum(grid_kwh)`.
  - [x] Recalculate `total_cost_bdt = sum(grid_kwh[h] * tariff[h])`.
  - [x] Recalculate `peak_grid_kwh = max(grid_kwh)`.
  - [x] Enforce tolerance ($\pm 0.05$ kWh / BDT).
- [x] Unit tested in `tests/test_verifier.py` (Passed all 10 sample cases + caught neutrality violation).

---

### Phase 5: FastAPI Application & Exact Schema Contracts (`app/main.py` & `app/schemas.py`)
- [x] Endpoint `GET /health`:
  - [x] Returns `{"status": "ok"}` with HTTP 200.
- [x] Endpoint `POST /optimize-energy`:
  - [x] Request validation using Pydantic.
  - [x] Orchestrates: LLM parsing -> Guardrails -> LP Optimization -> Replay Verifier -> Response generation.
  - [x] Returns exact JSON schema matching canonical specification.
  - [x] Handles bad JSON (400) and controlled internal errors (500 without leaking secrets or stack traces).

---

### Phase 6: Automated Testing & Validation (10 Sample Cases)
- [x] Write automated test suite running all 10 sample cases from `tests/sample_cases.json` against the FastAPI API.
- [x] Verify all 10 cases:
  - [x] Sample 1: Solar cleaning + distractor (Cost: 38365.0 BDT, Grid: 2692.5 kWh)
  - [x] Sample 2: Battery charging maintenance (Cost: 42885.0 BDT, Grid: 2915.0 kWh)
  - [x] Sample 3: Emergency reserve as percentage (Cost: 35480.0 BDT, Grid: 2430.0 kWh)
  - [x] Sample 4: No-discharge protection test (Cost: 40495.0 BDT, Grid: 2645.0 kWh)
  - [x] Sample 5: Temporary feeder grid cap (Cost: 33950.0 BDT, Grid: 2430.0 kWh)
  - [x] Sample 6: Multiple notes with distractor (Cost: 34090.0 BDT, Grid: 2395.0 kWh)
  - [x] Sample 7: Reserve plus transformer cap (Cost: 38550.0 BDT, Grid: 2560.0 kWh)
  - [x] Sample 8: Separate charge/discharge outages (Cost: 37665.0 BDT, Grid: 2490.0 kWh)
  - [x] Sample 9: Reduction wording normalization (Cost: 34873.0 BDT, Grid: 2504.0 kWh)
  - [x] Sample 10: Multi-constraint evening operation (Cost: 41620.0 BDT, Grid: 2715.0 kWh)
- [x] Verify latency: All 10 cases executed in **1.77 seconds** via HTTP client ($p95 < 0.2$s).
- [x] Complete repository test suite: **18 of 18 tests passed** in 4.85 seconds.

---

### Phase 7: Dockerization, Deployment & Documentation
- [x] Create production `Dockerfile`:
  - [x] Base image: `python:3.11-slim`
  - [x] Expose port `8000` (bind to `0.0.0.0`).
  - [x] Install system solvers (`coinor-cbc`) and pip dependencies.
  - [x] Zero secrets baked into image.
- [x] Create comprehensive `README.md` fulfilling 100% of documentation rubric:
  - [x] Quickstart copy-paste setup.
  - [x] Environment variables documentation.
  - [x] Architecture explanation (LLM -> Guardrails -> LP Optimizer -> Replay Verifier).
  - [x] Curl commands and test runner commands.
- [x] Git repository pushed to GitHub:
  - [x] Remote: `https://github.com/apu-22/BUP-CSE-SUST-Crusade.git`
  - [x] Commit: `feat: complete GridWise LLM energy scheduling pipeline with Gemini, PuLP optimizer, guardrails, and public test runner`
  - [x] Verified `.env` secret key is safely ignored and never committed.
- [ ] Deploy to public cloud platform (Render / Railway / Fly.io / GCP / VPS) to expose live endpoint.
- [ ] Push container image to Docker Hub / GHCR with exact tag.
- [ ] Prepare 3-Minute Architecture Video (Tie-Breaker).
