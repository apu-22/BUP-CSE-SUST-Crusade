import json
import pytest
from app.schemas import HourInput, BatteryInput, DirectiveInterpretation
from app.optimizer import optimize_energy_schedule


def test_optimizer_against_sample_cases():
    with open("tests/sample_cases.json", "r") as f:
        data = json.load(f)

    for case in data["cases"]:
        case_id = case["id"]
        inp = case["input"]
        exp = case["expected_output"]

        hours = [HourInput(**h) for h in inp["hours"]]
        battery = BatteryInput(**inp["battery"])
        directives = [DirectiveInterpretation(**d) for d in exp["directive_interpretation"]]

        plan, total_grid, total_cost, peak_grid = optimize_energy_schedule(
            hours=hours,
            battery=battery,
            directives=directives,
        )

        print(f"\n--- Testing {case_id} ({case.get('label')}) ---")
        print(f"Computed Cost: {total_cost} | Expected Cost: {exp['total_cost_bdt']}")
        print(f"Computed Grid: {total_grid} | Expected Grid: {exp['total_grid_kwh']}")
        print(f"Computed Peak: {peak_grid} | Expected Peak: {exp['peak_grid_kwh']}")

        # Re-calculated consistency checks (as required by rubric section 11.3)
        recalculated_grid = round(sum(p.grid_kwh for p in plan), 2)
        recalculated_cost = round(sum(p.grid_kwh * h.tariff_bdt_per_kwh for p, h in zip(plan, hours)), 2)
        recalculated_peak = round(max(p.grid_kwh for p in plan), 2)

        assert abs(total_grid - recalculated_grid) <= 0.01
        assert abs(total_cost - recalculated_cost) <= 0.01
        assert abs(peak_grid - recalculated_peak) <= 0.01

        # Check cost optimality against organizer ground truth
        assert abs(total_cost - exp["total_cost_bdt"]) <= 0.05, (
            f"Case {case_id} failed cost optimality: {total_cost} != {exp['total_cost_bdt']}"
        )
        assert abs(total_grid - exp["total_grid_kwh"]) <= 0.05, (
            f"Case {case_id} failed grid optimality: {total_grid} != {exp['total_grid_kwh']}"
        )


if __name__ == "__main__":
    test_optimizer_against_sample_cases()
    print("\n>>> ALL TEST CASES PASSED WITH 100% OPTIMALITY! <<<")
