# GridWise LLM — Smart Campus Energy Optimization

[![Tests](https://img.shields.io/badge/tests-18%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.13-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

> **BUP CSE Fest 2026 Hackathon — Preliminary Round**  
> An end-to-end pipeline combining **Google Gemini LLM directive interpretation**, **deterministic Python guardrails**, **PuLP/CBC Linear Programming optimization**, and **independent schedule replay verification**.

---

## 🏗️ Architecture & Pipeline

```
     [ Campus Operator Notes & 24h Energy Data ]
                          │
                          ▼
            POST /optimize-energy (FastAPI)
                          │
                          ▼
             ┌─────────────────────────┐
             │   LLM Interpreter       │  ◄── Google Gemini API (Single Batch Call)
             │   (Natural Language)    │
             └────────────┬────────────┘
                          │ Raw JSON Directives
                          ▼
             ┌─────────────────────────┐
             │ Deterministic Guardrail │  ◄── Strict Validation (Hours, Bounds,
             │ Validator               │      Remaining Factors, Enums)
             └────────────┬────────────┘
                          │ Valid Directives
                          ▼
             ┌─────────────────────────┐
             │ PuLP / CBC LP Optimizer │  ◄── Mathematical Energy Balance &
             │ (Deterministic Solver)  │      Cost Minimization
             └────────────┬────────────┘
                          │ Candidate Schedule
                          ▼
             ┌─────────────────────────┐
             │ Independent Replay      │  ◄── Verifies Energy Balance, Battery
             │ Verifier                │      Neutrality, Recalculates Totals
             └────────────┬────────────┘
                          │
                          ▼
                [ Canonical JSON Response ]
```

### Role of LLM vs Optimizer
- **What the LLM Does:** Understands human natural-language operator notes and extracts structured energy directives (`solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`).
- **What the LLM Does NOT Do:** The LLM **never** performs mathematical optimization, battery charge/discharge scheduling, or grid cost calculations. All mathematical scheduling is computed deterministically by Linear Programming (PuLP/CBC).

---

## 📋 Features

1. **Robust Paraphrase Understanding:** Handles diverse phrasing, relative percentage reductions (e.g. *"80% reduction"* $\rightarrow$ `factor: 0.2`), and percentage battery reserves.
2. **Distractor Filtering:** Irrelevant notes (e.g. cafeteria menus, sports events, meeting dates) are strictly mapped to `no_op` with `applies: false` and `structured_adjustment: null`.
3. **Deterministic Guardrails:** Rejects unsupported directives, enforces ascending `0..23` hours, checks non-negative energy bounds, and guarantees order preservation.
4. **100% Cost-Optimal LP Scheduling:** Formulated with PuLP/CBC; guarantees globally minimal grid electricity cost and zero dummy battery cycling.
5. **End-of-Day Neutrality:** Guaranteed by both the LP solver and the independent replay verifier ($E_{23} = E_{init}$).
6. **Sub-second to Low Latency ($p95 \le 3.5$s):** Batch processing sends all 1–3 notes in a single LLM request with resilient fallback.

---

## 🚀 Local Quickstart (Clean Environment)

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/apu-22/BUP-CSE-SUST-Crusade.git
cd BUP-CSE-SUST-Crusade

python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\activate
# On Linux / macOS:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and set your Gemini API key:
```bash
cp .env.example .env
```
Edit `.env`:
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
PORT=8000
HOST=0.0.0.0
```

> [!CAUTION]
> **Secret Handling:** Never commit `.env` or API keys. `.env` is ignored by `.gitignore`.

### 4. Run the API Server
```bash
python -m uvicorn app.main:app --reload --port 8000
```
- API Base URL: `http://localhost:8000`
- Interactive Swagger UI: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/health`

---

## 🧪 Testing & Validation

### Run Full Test Suite (18 Tests)
```bash
python -m pytest -v
```

### Run Public Sample Cases Runner (Against Live API)
Make sure the server is running on port 8000, then execute:

```bash
# Run all 10 public sample cases:
python tests/run_public_cases.py

# Run a single specific case:
python tests/run_public_cases.py SAMPLE-01
python tests/run_public_cases.py --case SAMPLE-03
```

**Sample Runner Output:**
```text
========================================
GridWise LLM Public Test Runner
========================================
API: http://localhost:8000/optimize-energy
Cases: 10

[1/10] SAMPLE-01
    Status: PASS
    HTTP: 200
    Time: 3.25s
    Cost: 38365.0 BDT | Grid: 2692.5 kWh

[2/10] SAMPLE-02
    Status: PASS
    HTTP: 200
    Time: 1.30s
    Cost: 42885.0 BDT | Grid: 2915.0 kWh
...
========================================
Summary
========================================
Total cases: 10
Passed: 10
Failed: 0
Average latency: 1.57s
Max latency:     3.75s
P95 latency:     2.86s
========================================
```

---

## 🐳 Docker Fallback Deployment

### Build Docker Image
```bash
docker build -t gridwise-service .
```

### Run Docker Container
```bash
docker run -d -p 8000:8000 -e GEMINI_API_KEY="your_api_key_here" --name gridwise gridwise-service
```

### Verify Container Health
```bash
curl http://localhost:8000/health
```

---

## 📡 API Contract

### 1. `GET /health`
Returns readiness status:
```json
{
  "status": "ok"
}
```

### 2. `POST /optimize-energy`
#### Request Example:
```json
{
  "scenario_id": "SAMPLE-01",
  "operator_notes": [
    "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
    "The sports office moved next month's registration deadline."
  ],
  "hours": [
    {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
    {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6}
  ],
  "battery": {
    "capacity_kwh": 220,
    "initial_energy_kwh": 110,
    "minimum_energy_kwh": 40,
    "max_charge_kwh_per_hour": 50,
    "max_discharge_kwh_per_hour": 50
  }
}
```

#### Response Example:
```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Rooftop solar panel cleaning from noon until 2 PM reduces usable solar output to 25% of forecast."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "Sports office registration deadline updates do not impact campus energy operations."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 90.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 110.0
    }
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Optimized schedule incorporating active directives (solar_reduction), satisfying battery neutrality and reducing total grid electricity cost."
}
```

---

## 🛡️ Supported Directives (Exhaustive)
1. **`solar_reduction`**: `{"hours": [...], "factor": number}` (Remaining usable fraction).
2. **`minimum_battery_reserve`**: `{"hours": [...], "minimum_energy_kwh": number}`.
3. **`no_charge_window`**: `{"hours": [...]}`.
4. **`no_discharge_window`**: `{"hours": [...]}`.
5. **`max_grid_window`**: `{"hours": [...], "max_grid_kwh": number}`.
6. **`no_op`**: `applies = false`, `structured_adjustment = null` (Distractor notes).

---

## 👥 Authors
- **Team SUST Crusade**
- BUP CSE Fest 2026 Hackathon
