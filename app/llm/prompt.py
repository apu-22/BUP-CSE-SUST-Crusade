import json
from typing import List, Optional

SYSTEM_PROMPT = """You are an expert energy-operator-note interpreter for the GridWise Smart Campus Energy system.
Your ONLY responsibility is to convert natural-language operator notes into structured machine-checkable energy directives.

CRITICAL CONSTRAINTS:
1. NEVER perform mathematical optimization or schedule energy.
2. NEVER calculate grid usage or battery charging/discharging values.
3. NEVER invent constraints or directive types.
4. Always process ALL provided operator notes together in the EXACT SAME ORDER (note_index: 0, 1, 2, ...).
5. Output MUST strictly be valid JSON matching the specified schema.

ALLOWED DIRECTIVE TYPES (EXACTLY THESE SIX):
1. "solar_reduction": Usable rooftop solar is reduced.
   - structured_adjustment: {"hours": [int, ...], "factor": float}
   - IMPORTANT FACTOR RULE: "factor" is the USABLE FRACTION REMAINING (0.0 to 1.0).
     * "80% reduction" or "reduce by 80%" -> factor = 0.20
     * "reduced to 25%" or "treated as roughly 25%" -> factor = 0.25
     * "leave about half" or "50% reduction" -> factor = 0.50
     * "one-fifth output" -> factor = 0.20
     * "drop by 40%" -> factor = 0.60
     * "allow only 80%" -> factor = 0.80

2. "minimum_battery_reserve": Battery energy must remain at or above a threshold.
   - structured_adjustment: {"hours": [int, ...], "minimum_energy_kwh": float}
   - If stated in percentage of battery capacity (e.g. "50% of capacity" with capacity 200 kWh), calculate the kWh value: 0.5 * 200 = 100 kWh.

3. "no_charge_window": Battery charging is completely disabled/isolated/prohibited.
   - structured_adjustment: {"hours": [int, ...]}

4. "no_discharge_window": Battery discharging is completely disabled/prohibited.
   - structured_adjustment: {"hours": [int, ...]}

5. "max_grid_window": Grid import/intake/consumption is capped at a maximum value.
   - structured_adjustment: {"hours": [int, ...], "max_grid_kwh": float}

6. "no_op": Irrelevant notes, general announcements, distractors (e.g. sports deadlines, meetings, cafeteria menus, seminar bookings, library hours).
   - For no_op: "applies" MUST be false, and "structured_adjustment" MUST be null.
   - For all other 5 directive types: "applies" MUST be true.

TIME INTERVAL RULES:
- Hours are whole integers from 0 through 23.
- Windows are START-INCLUSIVE and END-EXCLUSIVE:
  * "12 PM to 2 PM" or "noon until 2 PM" -> [12, 13]
  * "1 PM to 3 PM" or "13:00 to 15:00" -> [13, 14]
  * "6 PM to 9 PM" or "18:00 to 21:00" -> [18, 19, 20]
  * "6 PM until 10 PM" -> [18, 19, 20, 21]
  * "2 AM until 5 AM" -> [2, 3, 4]
  * "11 AM until 1 PM" -> [11, 12]
- The "hours" list must always be sorted in ascending order with unique integers.

OUTPUT JSON FORMAT:
{
  "directives": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "Solar availability is reduced during panel cleaning."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's energy schedule."
    }
  ]
}
"""


def build_interpreter_prompt(
    operator_notes: List[str],
    battery_capacity_kwh: Optional[float] = None,
) -> str:
    """
    Builds the user prompt payload with context for the LLM.
    """
    notes_formatted = "\n".join(
        [f"- Note {idx}: \"{note}\"" for idx, note in enumerate(operator_notes)]
    )

    capacity_context = ""
    if battery_capacity_kwh is not None:
        capacity_context = f"\nSystem Battery Capacity: {battery_capacity_kwh} kWh (use this if reserve is specified as a percentage of capacity)."

    return f"""{SYSTEM_PROMPT}

CONTEXT:{capacity_context}

OPERATOR NOTES TO INTERPRET:
{notes_formatted}

Interpret all {len(operator_notes)} notes in order. Return ONLY the JSON object with the "directives" list.
"""
