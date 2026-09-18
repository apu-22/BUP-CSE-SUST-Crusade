from typing import List, Dict, Any, Tuple
from app.schemas import (
    HourInput,
    BatteryInput,
    DirectiveInterpretation,
    HourlyPlanEntry,
)


class VerificationError(Exception):
    """Raised when an energy schedule violates physical, battery, or directive constraints."""
    pass


def verify_and_recalculate_schedule(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretation],
    hourly_plan: List[HourlyPlanEntry],
    tolerance: float = 0.05,
) -> Tuple[float, float, float]:
    """
    Independently replays the schedule against:
    1. Hourly energy balance: grid + solar_used + discharge == demand + charge
    2. Solar constraints: 0 <= solar_used <= effective_solar
    3. Battery bounds: min_reserve <= battery_energy_after <= capacity
    4. Battery rate limits: charge <= max_charge, discharge <= max_discharge
    5. Action consistency: charge/discharge/idle and battery_kwh values
    6. Battery state transition: E_after[h] == E_before[h] + charge - discharge
    7. End-of-day battery neutrality: E_after[23] == initial_energy_kwh
    8. All active directives: no_charge_window, no_discharge_window, min_reserve, max_grid

    Returns:
        (total_grid_kwh, total_cost_bdt, peak_grid_kwh)
        accurately recalculated from the verified hourly_plan.
    """
    if len(hourly_plan) != 24:
        raise VerificationError(f"hourly_plan must contain exactly 24 entries, got {len(hourly_plan)}")

    # 1. Recompute effective solar & directive limits
    effective_solar: List[float] = [float(h.solar_kwh) for h in hours]
    min_reserve: List[float] = [float(battery.minimum_energy_kwh) for _ in range(24)]
    no_charge_hours = set()
    no_discharge_hours = set()
    grid_caps: Dict[int, float] = {}

    for d in directives:
        if not d.applies or d.directive_type == "no_op" or not d.structured_adjustment:
            continue

        adj = d.structured_adjustment
        adj_dict = adj.model_dump() if hasattr(adj, "model_dump") else (adj if isinstance(adj, dict) else {})
        target_hours = adj_dict.get("hours", [])

        if d.directive_type == "solar_reduction":
            factor = float(adj_dict.get("factor", 1.0))
            for h in target_hours:
                if 0 <= h < 24:
                    effective_solar[h] = hours[h].solar_kwh * factor

        elif d.directive_type == "minimum_battery_reserve":
            req_min = float(adj_dict.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in target_hours:
                if 0 <= h < 24:
                    min_reserve[h] = max(min_reserve[h], req_min)

        elif d.directive_type == "no_charge_window":
            for h in target_hours:
                if 0 <= h < 24:
                    no_charge_hours.add(h)

        elif d.directive_type == "no_discharge_window":
            for h in target_hours:
                if 0 <= h < 24:
                    no_discharge_hours.add(h)

        elif d.directive_type == "max_grid_window":
            cap = float(adj_dict.get("max_grid_kwh", 1e9))
            for h in target_hours:
                if 0 <= h < 24:
                    if h in grid_caps:
                        grid_caps[h] = min(grid_caps[h], cap)
                    else:
                        grid_caps[h] = cap

    # 2. Replay hour by hour
    current_energy = float(battery.initial_energy_kwh)
    recalc_grid = 0.0
    recalc_cost = 0.0
    recalc_peak = 0.0

    for h in range(24):
        plan_entry = hourly_plan[h]
        if plan_entry.hour != h:
            raise VerificationError(f"Plan entry at index {h} has unexpected hour {plan_entry.hour}")

        g = float(plan_entry.grid_kwh)
        s = float(plan_entry.solar_used_kwh)
        action = plan_entry.battery_action
        b_kwh = float(plan_entry.battery_kwh)
        e_after = float(plan_entry.battery_energy_after_kwh)
        demand = float(hours[h].demand_kwh)
        tariff = float(hours[h].tariff_bdt_per_kwh)

        # Basic non-negative check
        if g < -tolerance or s < -tolerance or b_kwh < -tolerance or e_after < -tolerance:
            raise VerificationError(f"Hour {h}: Contains negative energy values.")

        # Solar constraint: 0 <= s <= effective_solar
        if s > effective_solar[h] + tolerance:
            raise VerificationError(
                f"Hour {h}: Solar used ({s:.2f} kWh) exceeds effective solar ({effective_solar[h]:.2f} kWh)."
            )

        # Charge and discharge parsing
        charge_kwh = b_kwh if action == "charge" else 0.0
        discharge_kwh = b_kwh if action == "discharge" else 0.0

        if action == "idle" and b_kwh > tolerance:
            raise VerificationError(f"Hour {h}: Action is idle but battery_kwh is {b_kwh}.")

        # Rate limits
        if charge_kwh > battery.max_charge_kwh_per_hour + tolerance:
            raise VerificationError(
                f"Hour {h}: Charge {charge_kwh:.2f} exceeds max charge rate {battery.max_charge_kwh_per_hour}."
            )
        if discharge_kwh > battery.max_discharge_kwh_per_hour + tolerance:
            raise VerificationError(
                f"Hour {h}: Discharge {discharge_kwh:.2f} exceeds max discharge rate {battery.max_discharge_kwh_per_hour}."
            )

        # Directive: no_charge_window
        if h in no_charge_hours and charge_kwh > tolerance:
            raise VerificationError(f"Hour {h}: Charging occurs during no_charge_window.")

        # Directive: no_discharge_window
        if h in no_discharge_hours and discharge_kwh > tolerance:
            raise VerificationError(f"Hour {h}: Discharging occurs during no_discharge_window.")

        # Directive: max_grid_window
        if h in grid_caps and g > grid_caps[h] + tolerance:
            raise VerificationError(f"Hour {h}: Grid import {g:.2f} exceeds max_grid cap {grid_caps[h]:.2f}.")

        # Energy balance: grid + solar_used + discharge == demand + charge
        supply = g + s + discharge_kwh
        consumption = demand + charge_kwh
        if abs(supply - consumption) > tolerance:
            raise VerificationError(
                f"Hour {h}: Energy balance violation. Supply={supply:.2f}, Demand={consumption:.2f}, Diff={abs(supply - consumption):.4f}"
            )

        # Battery state update & transition check
        expected_e_after = current_energy + charge_kwh - discharge_kwh
        if abs(e_after - expected_e_after) > tolerance:
            raise VerificationError(
                f"Hour {h}: Battery transition mismatch. Reported={e_after:.2f}, Expected={expected_e_after:.2f}"
            )

        # Battery bounds check
        if e_after < min_reserve[h] - tolerance:
            raise VerificationError(
                f"Hour {h}: Battery energy ({e_after:.2f} kWh) below required reserve ({min_reserve[h]:.2f} kWh)."
            )
        if e_after > battery.capacity_kwh + tolerance:
            raise VerificationError(
                f"Hour {h}: Battery energy ({e_after:.2f} kWh) exceeds capacity ({battery.capacity_kwh:.2f} kWh)."
            )

        # Update running state
        current_energy = e_after
        recalc_grid += g
        recalc_cost += g * tariff
        if g > recalc_peak:
            recalc_peak = g

    # 3. End of day neutrality: E_after[23] == initial_energy_kwh
    if abs(current_energy - battery.initial_energy_kwh) > tolerance:
        raise VerificationError(
            f"End-of-day battery neutrality violation. Final={current_energy:.2f} kWh, Initial={battery.initial_energy_kwh:.2f} kWh"
        )

    return round(recalc_grid, 2), round(recalc_cost, 2), round(recalc_peak, 2)
