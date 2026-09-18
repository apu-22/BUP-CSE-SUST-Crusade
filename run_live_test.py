"""
Live Manual Test Runner for GridWise
Runs end-to-end test with real Gemini API and PuLP Optimizer
"""
import json
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from app.main import app

load_dotenv()

def run_manual_test(case_id="SAMPLE-01"):
    with open("tests/sample_cases.json", "r") as f:
        cases = json.load(f)["cases"]

    selected_case = None
    for c in cases:
        if c["id"] == case_id:
            selected_case = c
            break

    if not selected_case:
        print(f"Case {case_id} not found.")
        return

    print("=" * 65)
    print(f" Running Manual Live Test: {case_id} - {selected_case.get('label')}")
    print("=" * 65)
    print("\nOperator Notes:")
    for i, note in enumerate(selected_case["input"]["operator_notes"]):
        print(f"  [{i}] {note}")

    print("\nCalling FastAPI endpoint with real Gemini 3.6 Flash & PuLP...")
    client = TestClient(app)
    response = client.post("/optimize-energy", json=selected_case["input"])

    if response.status_code != 200:
        print(f"\n[FAILED] HTTP {response.status_code}: {response.text}")
        return

    data = response.json()
    print("\n" + "-" * 65)
    print(" [SUCCESS] Received Optimal Energy Schedule!")
    print("-" * 65)
    print(f" Scenario ID:       {data['scenario_id']}")
    print(f" Total Grid Energy: {data['total_grid_kwh']} kWh (Expected: {selected_case['expected_output']['total_grid_kwh']} kWh)")
    print(f" Total Grid Cost:   {data['total_cost_bdt']} BDT (Expected: {selected_case['expected_output']['total_cost_bdt']} BDT)")
    print(f" Peak Grid Intake:  {data['peak_grid_kwh']} kWh")

    print("\n Extracted Directives (LLM + Guardrails):")
    for d in data["directive_interpretation"]:
        applies_str = "APPLIES" if d["applies"] else "IGNORED (no_op)"
        print(f"   Note {d['note_index']} [{applies_str}]: {d['directive_type']}")
        if d["structured_adjustment"]:
            print(f"      Adjustment: {d['structured_adjustment']}")
        print(f"      Reason: {d['explanation']}")

    print("\n Plan Summary:")
    print(f"   {data['plan_summary']}")
    print("=" * 65)


if __name__ == "__main__":
    import sys
    # Allow passing scenario ID like: python run_live_test.py SAMPLE-02
    target_case = sys.argv[1] if len(sys.argv) > 1 else "SAMPLE-01"
    run_manual_test(target_case)
