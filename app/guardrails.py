from typing import List, Dict, Any, Optional
from app.schemas import (
    DirectiveInterpretation,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
)


ALLOWED_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


class GuardrailValidationError(Exception):
    """Raised when structured LLM output fails deterministic validation."""
    pass


def validate_and_normalize_hours(hours: Any) -> List[int]:
    """
    Validates that hours is a list of unique integers 0..23, sorted in ascending order.
    Normalizes/sorts if needed.
    """
    if not isinstance(hours, list) or len(hours) == 0:
        raise GuardrailValidationError(f"'hours' must be a non-empty list of integers, got: {hours}")

    int_hours = []
    for h in hours:
        if not isinstance(h, (int, float)) or int(h) != h:
            raise GuardrailValidationError(f"Hour {h} must be an integer.")
        h_int = int(h)
        if not (0 <= h_int <= 23):
            raise GuardrailValidationError(f"Hour {h_int} is out of bounds [0, 23].")
        int_hours.append(h_int)

    # Check for unique and ascending
    unique_sorted = sorted(list(set(int_hours)))
    return unique_sorted


def validate_directive(
    raw: Dict[str, Any],
    expected_index: int,
    battery_capacity_kwh: Optional[float] = None,
) -> DirectiveInterpretation:
    """
    Deterministically validates a single raw directive dictionary.
    """
    directive_type = raw.get("directive_type")
    if directive_type not in ALLOWED_DIRECTIVE_TYPES:
        raise GuardrailValidationError(
            f"Unsupported directive_type '{directive_type}'. Allowed: {ALLOWED_DIRECTIVE_TYPES}"
        )

    explanation = raw.get("explanation") or f"Directive {directive_type} applied."
    note_index = raw.get("note_index", expected_index)
    if note_index != expected_index:
        note_index = expected_index

    # 1. no_op rule
    if directive_type == "no_op":
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=explanation,
        )

    # 2. Applicable directives must have applies=True
    applies = True

    # 3. Validate structured adjustment
    adj = raw.get("structured_adjustment")
    if not isinstance(adj, dict):
        raise GuardrailValidationError(
            f"Directive '{directive_type}' requires a structured_adjustment dictionary, got: {adj}"
        )

    hours = validate_and_normalize_hours(adj.get("hours", []))

    if directive_type == "solar_reduction":
        if "factor" not in adj:
            raise GuardrailValidationError("solar_reduction requires 'factor' field.")
        factor = float(adj["factor"])
        if not (0.0 <= factor <= 1.0):
            raise GuardrailValidationError(f"solar_reduction factor must be in [0.0, 1.0], got: {factor}")
        structured_adj = SolarReductionAdjustment(hours=hours, factor=round(factor, 4))

    elif directive_type == "minimum_battery_reserve":
        if "minimum_energy_kwh" not in adj:
            raise GuardrailValidationError("minimum_battery_reserve requires 'minimum_energy_kwh' field.")
        min_kwh = float(adj["minimum_energy_kwh"])
        if min_kwh < 0.0:
            raise GuardrailValidationError(f"minimum_energy_kwh must be non-negative, got: {min_kwh}")
        if battery_capacity_kwh is not None and min_kwh > battery_capacity_kwh:
            min_kwh = battery_capacity_kwh
        structured_adj = MinimumBatteryReserveAdjustment(hours=hours, minimum_energy_kwh=round(min_kwh, 2))

    elif directive_type in ("no_charge_window", "no_discharge_window"):
        structured_adj = WindowAdjustment(hours=hours)

    elif directive_type == "max_grid_window":
        if "max_grid_kwh" not in adj:
            raise GuardrailValidationError("max_grid_window requires 'max_grid_kwh' field.")
        max_grid = float(adj["max_grid_kwh"])
        if max_grid < 0.0:
            raise GuardrailValidationError(f"max_grid_kwh must be non-negative, got: {max_grid}")
        structured_adj = MaxGridAdjustment(hours=hours, max_grid_kwh=round(max_grid, 2))

    else:
        raise GuardrailValidationError(f"Unknown directive type: {directive_type}")

    return DirectiveInterpretation(
        note_index=note_index,
        applies=applies,
        directive_type=directive_type,
        structured_adjustment=structured_adj,
        explanation=explanation,
    )


def validate_directives_batch(
    raw_directives: List[Dict[str, Any]],
    expected_count: int,
    battery_capacity_kwh: Optional[float] = None,
) -> List[DirectiveInterpretation]:
    """
    Validates a full list of raw directives from the LLM, ensuring count, order, and schema.
    """
    if len(raw_directives) != expected_count:
        raise GuardrailValidationError(
            f"Expected {expected_count} directives matching input notes, got {len(raw_directives)}."
        )

    validated: List[DirectiveInterpretation] = []
    for i, raw_dict in enumerate(raw_directives):
        d = validate_directive(raw_dict, expected_index=i, battery_capacity_kwh=battery_capacity_kwh)
        validated.append(d)

    return validated
