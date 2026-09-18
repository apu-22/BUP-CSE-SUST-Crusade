import os
import json
import pytest
from typing import Dict, Any
from app.schemas import (
    DirectiveInterpretation,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
)
from app.guardrails import (
    validate_directive,
    validate_directives_batch,
    validate_and_normalize_hours,
    GuardrailValidationError,
)
from app.llm.provider import BaseLLMProvider
from app.llm.interpreter import LLMInterpreter


class MockLLMProvider(BaseLLMProvider):
    """
    Mock LLM provider for deterministic offline testing of interpreter and guardrails.
    """
    def __init__(self, response_data: Dict[str, Any]):
        self.response_data = response_data

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self.response_data)


# -------------------------------------------------------------
# Test 1: Solar Reduction (80% reduction -> factor 0.2, [12, 13])
# -------------------------------------------------------------
def test_case_1_solar_reduction():
    raw_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12, 13], "factor": 0.2},
        "explanation": "Solar generation reduced by 80% between 12 PM and 2 PM."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "solar_reduction"
    assert validated.applies is True
    assert isinstance(validated.structured_adjustment, SolarReductionAdjustment)
    assert validated.structured_adjustment.hours == [12, 13]
    assert validated.structured_adjustment.factor == 0.2


# -------------------------------------------------------------
# Test 2: Minimum Battery Reserve (100 kWh, 6 PM - 9 PM -> [18, 19, 20])
# -------------------------------------------------------------
def test_case_2_minimum_battery_reserve():
    raw_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "minimum_battery_reserve",
        "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 100},
        "explanation": "Keep battery reserve above 100 kWh."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "minimum_battery_reserve"
    assert validated.applies is True
    assert isinstance(validated.structured_adjustment, MinimumBatteryReserveAdjustment)
    assert validated.structured_adjustment.hours == [18, 19, 20]
    assert validated.structured_adjustment.minimum_energy_kwh == 100.0


# -------------------------------------------------------------
# Test 3: No-Charge Window (2 AM - 5 AM -> [2, 3, 4])
# -------------------------------------------------------------
def test_case_3_no_charge_window():
    raw_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "no_charge_window",
        "structured_adjustment": {"hours": [2, 3, 4]},
        "explanation": "No charging between 2 AM and 5 AM."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "no_charge_window"
    assert validated.applies is True
    assert isinstance(validated.structured_adjustment, WindowAdjustment)
    assert validated.structured_adjustment.hours == [2, 3, 4]


# -------------------------------------------------------------
# Test 4: No-Discharge Window (6 PM - 8 PM -> [18, 19])
# -------------------------------------------------------------
def test_case_4_no_discharge_window():
    raw_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "no_discharge_window",
        "structured_adjustment": {"hours": [18, 19]},
        "explanation": "Discharge prohibited from 6 PM to 8 PM."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "no_discharge_window"
    assert validated.applies is True
    assert isinstance(validated.structured_adjustment, WindowAdjustment)
    assert validated.structured_adjustment.hours == [18, 19]


# -------------------------------------------------------------
# Test 5: Max Grid Window (155 kWh, 6 PM - 9 PM -> [18, 19, 20])
# -------------------------------------------------------------
def test_case_5_max_grid_window():
    raw_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "max_grid_window",
        "structured_adjustment": {"hours": [18, 19, 20], "max_grid_kwh": 155},
        "explanation": "Grid capped at 155 kWh."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "max_grid_window"
    assert validated.applies is True
    assert isinstance(validated.structured_adjustment, MaxGridAdjustment)
    assert validated.structured_adjustment.hours == [18, 19, 20]
    assert validated.structured_adjustment.max_grid_kwh == 155.0


# -------------------------------------------------------------
# Test 6: Irrelevant Distractor Note -> no_op
# -------------------------------------------------------------
def test_case_6_no_op_distractor():
    raw_directive = {
        "note_index": 0,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "Campus meeting note does not affect energy schedule."
    }
    validated = validate_directive(raw_directive, expected_index=0)
    assert validated.directive_type == "no_op"
    assert validated.applies is False
    assert validated.structured_adjustment is None


# -------------------------------------------------------------
# Test 7: Multiple Notes in Single Request - Preserves Order & Count
# -------------------------------------------------------------
def test_case_7_multi_note_order_preservation():
    mock_response = {
        "directives": [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [10, 11], "factor": 0.5},
                "explanation": "50% solar reduction."
            },
            {
                "note_index": 1,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [14, 15]},
                "explanation": "No charging."
            },
            {
                "note_index": 2,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Library note."
            }
        ]
    }
    interpreter = LLMInterpreter(provider=MockLLMProvider(mock_response))
    notes = [
        "Cloud cover leaves about half solar forecast from 10 AM to noon.",
        "Charging circuit unavailable from 2 PM to 4 PM.",
        "Library extending book return hours."
    ]
    results = interpreter.interpret_notes(notes)

    assert len(results) == 3
    assert results[0].note_index == 0
    assert results[0].directive_type == "solar_reduction"
    assert results[1].note_index == 1
    assert results[1].directive_type == "no_charge_window"
    assert results[2].note_index == 2
    assert results[2].directive_type == "no_op"


# -------------------------------------------------------------
# Guardrail Security & Rejection Tests
# -------------------------------------------------------------
def test_guardrail_rejects_unsupported_directive():
    bad_directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "arbitrary_unsupported_directive",
        "structured_adjustment": {"hours": [1, 2]},
    }
    with pytest.raises(GuardrailValidationError, match="Unsupported directive_type"):
        validate_directive(bad_directive, expected_index=0)


def test_guardrail_rejects_out_of_bounds_hours():
    with pytest.raises(GuardrailValidationError, match="out of bounds"):
        validate_and_normalize_hours([22, 23, 24])


def test_guardrail_rejects_invalid_solar_factor():
    bad_solar = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12], "factor": 1.5},
    }
    with pytest.raises(GuardrailValidationError, match="factor must be in"):
        validate_directive(bad_solar, expected_index=0)


def test_guardrail_rejects_negative_grid_cap():
    bad_grid = {
        "note_index": 0,
        "applies": True,
        "directive_type": "max_grid_window",
        "structured_adjustment": {"hours": [12], "max_grid_kwh": -10},
    }
    with pytest.raises(GuardrailValidationError, match="must be non-negative"):
        validate_directive(bad_grid, expected_index=0)


def test_guardrail_rejects_count_mismatch():
    raw_directives = [
        {"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None}
    ]
    with pytest.raises(GuardrailValidationError, match="Expected 2 directives"):
        validate_directives_batch(raw_directives, expected_count=2)
