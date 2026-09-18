import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from dotenv import load_dotenv

from app.schemas import (
    HealthResponse,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.llm.interpreter import LLMInterpreter
from app.llm.provider import GeminiProvider, LLMProviderError
from app.guardrails import GuardrailValidationError
from app.optimizer import optimize_energy_schedule, OptimizationError
from app.verifier import verify_and_recalculate_schedule, VerificationError

load_dotenv()

# Setup structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GridWise")

app = FastAPI(
    title="GridWise — Smart Campus Energy Optimization",
    description="LLM-Assisted Operator Directive Interpretation and 24-Hour Energy Scheduling API",
    version="2.0",
)

# Global Interpreter instance using GeminiProvider
interpreter = LLMInterpreter(provider=GeminiProvider())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Returns HTTP 400 for structurally invalid or malformed requests according to spec.
    """
    logger.warning(f"Request validation failed: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed JSON or structurally invalid request."},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Returns controlled HTTP 500 without leaking secrets, stack traces, or credentials.
    """
    logger.error(f"Internal server error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal optimization service error."},
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Readiness and health check endpoint for judge harness.
    """
    return HealthResponse(status="ok")


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
async def optimize_energy(payload: OptimizeEnergyRequest):
    """
    Main GridWise endpoint:
    1. Extracts structured directives from operator notes using LLM.
    2. Deterministically validates directives against strict guardrails.
    3. Solves optimal 24-hour schedule via PuLP Linear Programming.
    4. Independently verifies energy balance, battery neutrality, and recalculates totals.
    5. Returns exact canonical JSON response.
    """
    logger.info(f"Processing optimization request for scenario: {payload.scenario_id}")

    # 1. LLM Interpretation + Deterministic Guardrail Validation
    try:
        directives = interpreter.interpret_notes(
            operator_notes=payload.operator_notes,
            battery_capacity_kwh=payload.battery.capacity_kwh,
        )
    except (LLMProviderError, GuardrailValidationError) as e:
        logger.error(f"Directive interpretation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to interpret operator notes safely.",
        )

    # 2. Linear Programming Optimization
    try:
        raw_plan, total_grid, total_cost, peak_grid = optimize_energy_schedule(
            hours=payload.hours,
            battery=payload.battery,
            directives=directives,
        )
    except OptimizationError as e:
        logger.error(f"Optimization solving failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Optimization model could not find a feasible schedule.",
        )

    # 3. Independent Replay & Recalculation Verification
    try:
        recalc_grid, recalc_cost, recalc_peak = verify_and_recalculate_schedule(
            hours=payload.hours,
            battery=payload.battery,
            directives=directives,
            hourly_plan=raw_plan,
        )
    except VerificationError as e:
        logger.error(f"Schedule verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Schedule failed physical energy or neutrality verification.",
        )

    # 4. Generate plan summary
    active_types = [d.directive_type for d in directives if d.applies and d.directive_type != "no_op"]
    if active_types:
        summary = (
            f"Optimized schedule incorporating active directives ({', '.join(active_types)}), "
            f"satisfying battery neutrality and reducing total grid electricity cost."
        )
    else:
        summary = "Standard optimal schedule minimizing grid cost while maintaining battery neutrality."

    return OptimizeEnergyResponse(
        scenario_id=payload.scenario_id,
        directive_interpretation=directives,
        hourly_plan=raw_plan,
        total_grid_kwh=recalc_grid,
        total_cost_bdt=recalc_cost,
        peak_grid_kwh=recalc_peak,
        plan_summary=summary,
    )
