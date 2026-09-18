import json
import pytest
from fastapi.testclient import TestClient
from app.main import app, interpreter
from app.llm.provider import BaseLLMProvider


class MockSampleCasesProvider(BaseLLMProvider):
    """
    Mock provider that returns the ground-truth directive interpretation
    for each sample case, ensuring fast offline end-to-end integration testing.
    """
    def __init__(self, sample_cases_dict):
        self.sample_cases_dict = sample_cases_dict

    def generate_json(self, prompt: str) -> str:
        # Match prompt with scenario
        for case in self.sample_cases_dict.values():
            if case["input"]["scenario_id"] in prompt or case["input"]["operator_notes"][0] in prompt:
                directives = case["expected_output"]["directive_interpretation"]
                return json.dumps({"directives": directives})
        # Default fallback
        return json.dumps({"directives": []})


@pytest.fixture(autouse=True)
def setup_mock_interpreter():
    with open("tests/sample_cases.json", "r") as f:
        cases_list = json.load(f)["cases"]
    cases_dict = {c["id"]: c for c in cases_list}

    original_provider = interpreter.provider
    interpreter.provider = MockSampleCasesProvider(cases_dict)
    yield
    interpreter.provider = original_provider


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_malformed_request_returns_400():
    # Missing required battery and hours fields
    bad_payload = {"scenario_id": "TEST-BAD", "operator_notes": ["Test note"]}
    response = client.post("/optimize-energy", json=bad_payload)
    assert response.status_code == 400


def test_all_10_sample_cases_end_to_end():
    with open("tests/sample_cases.json", "r") as f:
        cases = json.load(f)["cases"]

    for case in cases:
        case_id = case["id"]
        inp = case["input"]
        exp = case["expected_output"]

        response = client.post("/optimize-energy", json=inp)
        assert response.status_code == 200, f"Case {case_id} failed with {response.text}"

        data = response.json()

        # 1. Echo scenario_id
        assert data["scenario_id"] == case_id

        # 2. Check directive interpretation
        exp_dirs = exp["directive_interpretation"]
        act_dirs = data["directive_interpretation"]
        assert len(act_dirs) == len(exp_dirs)
        for i in range(len(exp_dirs)):
            assert act_dirs[i]["note_index"] == i
            assert act_dirs[i]["applies"] == exp_dirs[i]["applies"]
            assert act_dirs[i]["directive_type"] == exp_dirs[i]["directive_type"]

        # 3. Check 24 hours plan
        assert len(data["hourly_plan"]) == 24
        for h, plan in enumerate(data["hourly_plan"]):
            assert plan["hour"] == h
            assert plan["battery_action"] in ("charge", "discharge", "idle")

        # 4. Check cost and grid optimality against organizer reference
        assert abs(data["total_cost_bdt"] - exp["total_cost_bdt"]) <= 0.05, (
            f"Case {case_id} cost mismatch: {data['total_cost_bdt']} vs {exp['total_cost_bdt']}"
        )
        assert abs(data["total_grid_kwh"] - exp["total_grid_kwh"]) <= 0.05, (
            f"Case {case_id} grid mismatch: {data['total_grid_kwh']} vs {exp['total_grid_kwh']}"
        )

        print(f"E2E API Test Passed: {case_id} | Cost: {data['total_cost_bdt']} BDT | Grid: {data['total_grid_kwh']} kWh")
