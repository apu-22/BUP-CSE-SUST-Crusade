import json
import pytest
from app.schemas import HourInput, BatteryInput, DirectiveInterpretation
from app.optimizer import optimize_energy_schedule
from app.verifier import verify_and_recalculate_schedule, VerificationError


def test_verifier_on_all_sample_cases():
    with open("tests/sample_cases.json", "r") as f:
        data = json.load(f)

    for case in data["cases"]:
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

        recalc_grid, recalc_cost, recalc_peak = verify_and_recalculate_schedule(
            hours=hours,
            battery=battery,
            directives=directives,
            hourly_plan=plan,
        )

        assert abs(recalc_grid - exp["total_grid_kwh"]) <= 0.05
        assert abs(recalc_cost - exp["total_cost_bdt"]) <= 0.05
        assert abs(recalc_peak - peak_grid) <= 0.05


def test_verifier_catches_neutrality_violation():
    with open("tests/sample_cases.json", "r") as f:
        case = json.load(f)["cases"][0]

    hours = [HourInput(**h) for h in case["input"]["hours"]]
    battery = BatteryInput(**case["input"]["battery"])
    directives = [DirectiveInterpretation(**d) for d in case["expected_output"]["directive_interpretation"]]

    plan, _, _, _ = optimize_energy_schedule(hours=hours, battery=battery, directives=directives)

    # Tamper with hour 23 battery energy to break end-of-day neutrality
    plan[23].battery_energy_after_kwh += 10.0

    with pytest.raises(VerificationError, match="battery neutrality violation|Battery transition mismatch"):
        verify_and_recalculate_schedule(hours, battery, directives, plan)
