from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


# -------------------------------------------------------------
# Health Check Schema
# -------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = "ok"


# -------------------------------------------------------------
# Request Schemas
# -------------------------------------------------------------
class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Unique integer from 0 to 23")
    demand_kwh: float = Field(..., ge=0, description="Campus demand that must be supplied in this hour")
    solar_kwh: float = Field(..., ge=0, description="Base solar energy available before operator-note adjustments")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity price for this hour")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum energy the battery can store")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at the start of hour 0")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base reserve level the battery must never go below")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum energy that may be added in one hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum energy that may be removed in one hour")


class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique synthetic scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1 to 3 operator notes")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="24 hourly entries for hours 0..23")
    battery: BatteryInput

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        if len(v) != 24:
            raise ValueError("hours array must contain exactly 24 entries.")
        hours_found = [h.hour for h in v]
        if hours_found != list(range(24)):
            raise ValueError("hours must contain unique entries for hours 0 through 23 in sequence.")
        return v


# -------------------------------------------------------------
# Directive & Adjustment Schemas
# -------------------------------------------------------------
DirectiveTypeEnum = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    factor: float = Field(..., ge=0.0, le=1.0, description="Usable fraction remaining (e.g., 0.25)")


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Required minimum battery energy in kWh")


class WindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")


class MaxGridAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    max_grid_kwh: float = Field(..., ge=0.0, description="Maximum grid import allowed in kWh")


StructuredAdjustmentType = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
    Dict[str, Any],
    None
]


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index of corresponding operator note")
    applies: bool = Field(..., description="true for applicable non-no_op directives, false only for no_op")
    directive_type: DirectiveTypeEnum
    structured_adjustment: Optional[StructuredAdjustmentType] = None
    explanation: str = Field(..., description="Short explanation of interpretation")


# -------------------------------------------------------------
# Response Schemas
# -------------------------------------------------------------
BatteryActionEnum = Literal["charge", "discharge", "idle"]


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0)
    solar_used_kwh: float = Field(..., ge=0.0)
    battery_action: BatteryActionEnum
    battery_kwh: float = Field(..., ge=0.0)
    battery_energy_after_kwh: float = Field(..., ge=0.0)


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
