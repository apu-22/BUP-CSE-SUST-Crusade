from typing import List, Dict, Any, Tuple
import pulp
from app.schemas import (
    HourInput,
    BatteryInput,
    DirectiveInterpretation,
    HourlyPlanEntry,
)


class OptimizationError(Exception):
    pass


def optimize_energy_schedule(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretation],
) -> Tuple[List[HourlyPlanEntry], float, float, float]:
    """
    Formulates and solves the 24-hour Linear Program for the GridWise challenge.
    Returns:
        (hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh)
    """
    # 1. Initialize effective constraints across 24 hours
    effective_solar: List[float] = [float(h.solar_kwh) for h in hours]
    min_reserve: List[float] = [float(battery.minimum_energy_kwh) for _ in range(24)]
    allow_charge: List[bool] = [True] * 24
    allow_discharge: List[bool] = [True] * 24
    grid_caps: Dict[int, float] = {}

    # 2. Apply structured adjustments from active directives
    for d in directives:
        if not d.applies or d.directive_type == "no_op" or not d.structured_adjustment:
            continue

        adj = d.structured_adjustment
        # Support both Pydantic model and raw dict
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
                    allow_charge[h] = False

        elif d.directive_type == "no_discharge_window":
            for h in target_hours:
                if 0 <= h < 24:
                    allow_discharge[h] = False

        elif d.directive_type == "max_grid_window":
            cap = float(adj_dict.get("max_grid_kwh", 1e9))
            for h in target_hours:
                if 0 <= h < 24:
                    if h in grid_caps:
                        grid_caps[h] = min(grid_caps[h], cap)
                    else:
                        grid_caps[h] = cap

    # 3. Create PuLP LP Model
    prob = pulp.LpProblem("GridWise_24h_Optimization", pulp.LpMinimize)

    # Decision variables for each hour h in 0..23
    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0.0) for h in range(24)]
    solar_used = [
        pulp.LpVariable(f"solar_used_{h}", lowBound=0.0, upBound=effective_solar[h])
        for h in range(24)
    ]
    charge = [
        pulp.LpVariable(
            f"charge_{h}",
            lowBound=0.0,
            upBound=battery.max_charge_kwh_per_hour if allow_charge[h] else 0.0,
        )
        for h in range(24)
    ]
    discharge = [
        pulp.LpVariable(
            f"discharge_{h}",
            lowBound=0.0,
            upBound=battery.max_discharge_kwh_per_hour if allow_discharge[h] else 0.0,
        )
        for h in range(24)
    ]
    soc = [
        pulp.LpVariable(
            f"soc_{h}",
            lowBound=min_reserve[h],
            upBound=battery.capacity_kwh,
        )
        for h in range(24)
    ]

    # 4. Constraints

    # Grid caps from max_grid_window
    for h, cap in grid_caps.items():
        prob += (grid[h] <= cap, f"GridCap_{h}")

    # Energy balance & battery state transition per hour
    for h in range(24):
        demand_h = float(hours[h].demand_kwh)

        # Energy balance: grid + solar_used + discharge == demand + charge
        prob += (
            grid[h] + solar_used[h] + discharge[h] == demand_h + charge[h],
            f"EnergyBalance_{h}",
        )

        # Battery state equation:
        # soc[h] == soc[h-1] + charge[h] - discharge[h]
        if h == 0:
            prob += (
                soc[0] == battery.initial_energy_kwh + charge[0] - discharge[0],
                "BatteryState_0",
            )
        else:
            prob += (
                soc[h] == soc[h - 1] + charge[h] - discharge[h],
                f"BatteryState_{h}",
            )

    # End of day battery neutrality: E_after[23] == initial_energy_kwh
    prob += (
        soc[23] == battery.initial_energy_kwh,
        "EndOfDay_BatteryNeutrality",
    )

    # 5. Objective Function: Minimize total grid electricity cost
    # A tiny weight (1e-5) on (charge + discharge) eliminates null-space degeneracy
    # and strictly prohibits simultaneous charging and discharging.
    tariffs = [float(h.tariff_bdt_per_kwh) for h in hours]
    cost_expr = pulp.lpSum([
        grid[h] * tariffs[h] + 1e-5 * (charge[h] + discharge[h])
        for h in range(24)
    ])
    prob += cost_expr

    # 6. Solve LP Model using CBC
    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)

    if status != pulp.LpStatusOptimal:
        raise OptimizationError(
            f"LP Optimizer failed to find an optimal feasible schedule. Status: {pulp.LpStatus[status]}"
        )

    # 7. Extract Solution and build HourlyPlan
    hourly_plan: List[HourlyPlanEntry] = []
    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0

    TOL = 1e-4

    for h in range(24):
        g_val = float(pulp.value(grid[h]))
        s_val = float(pulp.value(solar_used[h]))
        c_val = float(pulp.value(charge[h]))
        d_val = float(pulp.value(discharge[h]))
        e_val = float(pulp.value(soc[h]))

        # Clean tiny numerical noise from solver
        g_val = max(0.0, round(g_val, 4))
        s_val = max(0.0, round(s_val, 4))
        c_val = max(0.0, round(c_val, 4))
        d_val = max(0.0, round(d_val, 4))
        e_val = max(0.0, round(e_val, 4))

        if c_val > TOL:
            action = "charge"
            b_kwh = c_val
        elif d_val > TOL:
            action = "discharge"
            b_kwh = d_val
        else:
            action = "idle"
            b_kwh = 0.0

        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=g_val,
                solar_used_kwh=s_val,
                battery_action=action,
                battery_kwh=b_kwh,
                battery_energy_after_kwh=e_val,
            )
        )

        total_grid_kwh += g_val
        total_cost_bdt += g_val * tariffs[h]
        if g_val > peak_grid_kwh:
            peak_grid_kwh = g_val

    # Clean totals
    total_grid_kwh = round(total_grid_kwh, 2)
    total_cost_bdt = round(total_cost_bdt, 2)
    peak_grid_kwh = round(peak_grid_kwh, 2)

    return hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh
