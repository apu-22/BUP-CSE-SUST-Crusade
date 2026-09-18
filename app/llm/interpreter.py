import json
import re
from typing import List, Optional, Dict, Any
from app.schemas import DirectiveInterpretation
from app.llm.provider import BaseLLMProvider, GeminiProvider, LLMProviderError
from app.llm.prompt import build_interpreter_prompt
from app.guardrails import validate_directives_batch, GuardrailValidationError


class LLMInterpreter:
    """
    Coordinates prompt construction, single-call batch LLM execution,
    and deterministic guardrail validation.
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        self.provider = provider or GeminiProvider()

    def interpret_notes(
        self,
        operator_notes: List[str],
        battery_capacity_kwh: Optional[float] = None,
    ) -> List[DirectiveInterpretation]:
        """
        Interprets 1 to 3 operator notes in a SINGLE LLM API call.
        Returns validated, machine-checkable DirectiveInterpretation objects.
        """
        if not operator_notes:
            return []

        # 1. Build prompt for all notes in one batch
        prompt = build_interpreter_prompt(
            operator_notes=operator_notes,
            battery_capacity_kwh=battery_capacity_kwh,
        )

        # 2. Call LLM provider
        raw_json_str = self.provider.generate_json(prompt)

        # 3. Parse JSON response
        try:
            parsed = json.loads(raw_json_str)
        except json.JSONDecodeError:
            # Attempt to extract JSON substring if surrounded by markdown code blocks
            match = re.search(r"\{.*\}", raw_json_str, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
            else:
                raise LLMProviderError(f"Malformed JSON returned by LLM: {raw_json_str}")

        if isinstance(parsed, dict) and "directives" in parsed:
            raw_directives = parsed["directives"]
        elif isinstance(parsed, list):
            raw_directives = parsed
        else:
            raise LLMProviderError(f"Unexpected JSON structure from LLM: {parsed}")

        # 4. Pass through strict Deterministic Guardrails
        validated_directives = validate_directives_batch(
            raw_directives=raw_directives,
            expected_count=len(operator_notes),
            battery_capacity_kwh=battery_capacity_kwh,
        )

        return validated_directives
