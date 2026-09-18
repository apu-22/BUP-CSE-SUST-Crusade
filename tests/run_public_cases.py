"""
Standalone Public Test Runner for GridWise LLM Hackathon

Executes public sample cases against the deployed / local GridWise API endpoint
and performs strict deterministic schema & replay verification.

Usage:
    python tests/run_public_cases.py
    python tests/run_public_cases.py SAMPLE-01
    python tests/run_public_cases.py --case SAMPLE-03
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import httpx

# Add project root to sys.path to import existing verifier and schemas
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import (
    HourInput,
    BatteryInput,
    DirectiveInterpretation,
    HourlyPlanEntry,
    OptimizeEnergyResponse,
)
from app.verifier import verify_and_recalculate_schedule, VerificationError


def load_public_cases() -> List[Dict[str, Any]]:
    """
    Locates and loads public test cases from sample_cases/public_cases.json
    or fallback tests/sample_cases.json.
    """
    candidates = [
        PROJECT_ROOT / "sample_cases" / "public_cases.json",
        PROJECT_ROOT / "tests" / "sample_cases.json",
    ]
    for p in candidates:
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("cases", [])
    raise FileNotFoundError("Could not find public_cases.json in sample_cases/ or tests/")


def calculate_p95(latencies: List[float]) -> float:
    """
    Computes 95th percentile latency safely, even for small lists.
    """
    if not latencies:
        return 0.0
    sorted_lat = sorted(latencies)
    k = (len(sorted_lat) - 1) * 0.95
    f = int(k)
    c = min(f + 1, len(sorted_lat) - 1)
    d = k - f
    return sorted_lat[f] + d * (sorted_lat[c] - sorted_lat[f])


def validate_response(
    request_data: Dict[str, Any],
    response_data: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """
    Validates the API response against Pydantic response schema
    and re-runs the physical schedule replay verifier.
    """
    try:
        # 1. Structural schema validation via Pydantic model
        resp_model = OptimizeEnergyResponse(**response_data)
    except Exception as e:
        return False, f"Schema validation failed: {e}"

    # 2. Check scenario_id echo
    if resp_model.scenario_id != request_data.get("scenario_id"):
        return False, (
            f"Scenario ID mismatch: returned '{resp_model.scenario_id}', "
            f"expected '{request_data.get('scenario_id')}'"
        )

    # 3. Check directive count and order
    req_notes = request_data.get("operator_notes", [])
    if len(resp_model.directive_interpretation) != len(req_notes):
        return False, (
            f"Directive count mismatch: expected {len(req_notes)}, "
            f"got {len(resp_model.directive_interpretation)}"
        )
    for idx, d in enumerate(resp_model.directive_interpretation):
        if d.note_index != idx:
            return False, f"Directive at position {idx} has invalid note_index {d.note_index}"

    # 4. Check 24-hour structure
    if len(resp_model.hourly_plan) != 24:
        return False, f"Hourly plan must have 24 hours, got {len(resp_model.hourly_plan)}"

    # 5. Independent Replay Verification
    try:
        hours = [HourInput(**h) for h in request_data["hours"]]
        battery = BatteryInput(**request_data["battery"])
        directives = resp_model.directive_interpretation
        plan = resp_model.hourly_plan

        recalc_grid, recalc_cost, recalc_peak = verify_and_recalculate_schedule(
            hours=hours,
            battery=battery,
            directives=directives,
            hourly_plan=plan,
            tolerance=0.05,
        )

        # Check recalculated consistency
        if abs(resp_model.total_cost_bdt - recalc_cost) > 0.10:
            return False, (
                f"Reported total_cost_bdt ({resp_model.total_cost_bdt}) does not match "
                f"recalculated cost ({recalc_cost})"
            )
        if abs(resp_model.total_grid_kwh - recalc_grid) > 0.10:
            return False, (
                f"Reported total_grid_kwh ({resp_model.total_grid_kwh}) does not match "
                f"recalculated grid ({recalc_grid})"
            )
    except VerificationError as ve:
        return False, f"Replay verification failed: {ve}"
    except Exception as ex:
        return False, f"Replay verification exception: {ex}"

    return True, None


def main():
    parser = argparse.ArgumentParser(description="GridWise LLM Public Test Runner")
    parser.add_argument(
        "case_pos",
        nargs="?",
        help="Optional positional case ID (e.g. SAMPLE-01)",
    )
    parser.add_argument(
        "--case",
        "-c",
        dest="case_opt",
        help="Specific case ID to run (e.g. SAMPLE-02)",
    )
    args = parser.parse_args()

    target_case_id = args.case_opt or args.case_pos

    # Determine Base API URL
    base_url = os.getenv("GRIDWISE_API_URL", "http://localhost:8000").rstrip("/")
    api_endpoint = f"{base_url}/optimize-energy"

    # Load Cases
    all_cases = load_public_cases()
    if target_case_id:
        cases = [c for c in all_cases if c["id"] == target_case_id]
        if not cases:
            print(f"Error: Target case '{target_case_id}' not found in public cases.")
            sys.exit(1)
    else:
        cases = all_cases

    print("========================================")
    print("GridWise LLM Public Test Runner")
    print("========================================")
    print(f"API: {api_endpoint}")
    print(f"Cases: {len(cases)}")
    print()

    passed_count = 0
    failed_count = 0
    latencies: List[float] = []

    # Configure HTTP client with 30-second timeout
    with httpx.Client(timeout=30.0) as client:
        for idx, case in enumerate(cases, 1):
            case_id = case["id"]
            input_payload = case["input"]

            print(f"[{idx}/{len(cases)}] {case_id}")

            start_time = time.perf_counter()
            try:
                response = client.post(api_endpoint, json=input_payload)
                elapsed = time.perf_counter() - start_time
                latencies.append(elapsed)

                http_code = response.status_code

                if http_code == 200:
                    try:
                        resp_json = response.json()
                        valid, error_msg = validate_response(input_payload, resp_json)
                        if valid:
                            passed_count += 1
                            print("    Status: PASS")
                            print(f"    HTTP: {http_code}")
                            print(f"    Time: {elapsed:.2f}s")
                            print(f"    Cost: {resp_json.get('total_cost_bdt')} BDT | Grid: {resp_json.get('total_grid_kwh')} kWh")
                        else:
                            failed_count += 1
                            print("    Status: FAIL")
                            print(f"    HTTP: {http_code}")
                            print(f"    Time: {elapsed:.2f}s")
                            print(f"    Reason: {error_msg}")
                    except json.JSONDecodeError:
                        failed_count += 1
                        print("    Status: FAIL")
                        print(f"    HTTP: {http_code}")
                        print(f"    Time: {elapsed:.2f}s")
                        print("    Reason: Invalid JSON received from API")
                else:
                    failed_count += 1
                    print("    Status: FAIL")
                    print(f"    HTTP: {http_code}")
                    print(f"    Time: {elapsed:.2f}s")
                    # Safe truncation of error response body
                    body_snippet = response.text[:300].replace("\n", " ")
                    print(f"    Response: {body_snippet}")

            except httpx.ConnectError:
                elapsed = time.perf_counter() - start_time
                failed_count += 1
                print("    Status: FAIL")
                print("    HTTP: Connection Error")
                print(f"    Time: {elapsed:.2f}s")
                print(f"    Reason: Could not connect to {api_endpoint}. Is the server running?")
            except httpx.TimeoutException:
                elapsed = time.perf_counter() - start_time
                failed_count += 1
                print("    Status: FAIL")
                print("    HTTP: Timeout")
                print(f"    Time: {elapsed:.2f}s")
                print("    Reason: Request exceeded 30.0s timeout limit.")
            except Exception as ex:
                elapsed = time.perf_counter() - start_time
                failed_count += 1
                print("    Status: FAIL")
                print("    HTTP: Error")
                print(f"    Time: {elapsed:.2f}s")
                print(f"    Reason: {ex}")

            print()

    # Latency statistics
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    max_lat = max(latencies) if latencies else 0.0
    p95_lat = calculate_p95(latencies)

    print("========================================")
    print("Summary")
    print("========================================")
    print(f"Total cases: {len(cases)}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    print(f"Average latency: {avg_lat:.2f}s")
    print(f"Max latency:     {max_lat:.2f}s")
    print(f"P95 latency:     {p95_lat:.2f}s")
    print("========================================")

    # Exit code according to rubric / CI requirement
    if failed_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
