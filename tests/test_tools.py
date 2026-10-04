from types import SimpleNamespace

import app.agent as agent_module
from app.database import reset_demo_data
from app.tools import (
    get_invoice,
    reset_update_failure_state,
    search_invoices,
    update_finance_record,
    verify_finance_record,
)


def setup_function() -> None:
    reset_demo_data()
    reset_update_failure_state()


def test_search_invoices() -> None:
    result = search_invoices("Acme Corp")
    assert result["success"] is True
    assert result["count"] >= 3
    assert all(invoice["company"] == "Acme Corp" for invoice in result["invoices"])


def test_get_invoice() -> None:
    result = search_invoices("Acme Corp")
    invoice_id = result["invoices"][0]["id"]
    invoice = get_invoice(invoice_id)
    assert invoice["success"] is True
    assert invoice["invoice"]["id"] == invoice_id


def test_update_finance_record() -> None:
    first = update_finance_record("INV-2026-004", 56000.0, "2026-11-02")
    assert first["success"] is False
    assert first["retryable"] is True

    second = update_finance_record("INV-2026-004", 56000.0, "2026-11-02")
    assert second["success"] is True
    assert second["finance_record"]["invoice_number"] == "INV-2026-004"


def test_verify_finance_record() -> None:
    update_finance_record("INV-2026-004", 56000.0, "2026-11-02")
    update_finance_record("INV-2026-004", 56000.0, "2026-11-02")
    result = verify_finance_record("INV-2026-004")
    assert result["success"] is True
    assert result["record"]["amount"] == 56000.0


def test_retry_behavior() -> None:
    first = update_finance_record("INV-2026-003", 84500.0, "2026-10-20")
    second = update_finance_record("INV-2026-003", 84500.0, "2026-10-20")
    assert first["success"] is False
    assert second["success"] is True


def test_llm_tool_path_is_primary(monkeypatch) -> None:
    reset_demo_data()
    reset_update_failure_state()

    invoice_id = search_invoices("Acme Corp")["invoices"][0]["id"]
    responses = iter(
        [
            [{"function": {"name": "search_invoices", "arguments": '{"company": "Acme Corp"}' } }],
            [{"function": {"name": "get_invoice", "arguments": f'{{"invoice_id": {invoice_id}}}' } }],
            [{"function": {"name": "update_finance_record", "arguments": '{"invoice_number": "INV-2026-004", "amount": 56000.0, "due_date": "2026-11-02"}' } }],
            [{"function": {"name": "update_finance_record", "arguments": '{"invoice_number": "INV-2026-004", "amount": 56000.0, "due_date": "2026-11-02"}' } }],
            [{"function": {"name": "verify_finance_record", "arguments": '{"invoice_number": "INV-2026-004"}' } }],
        ]
    )

    class FakeCompletions:
        def create(self, messages, tools, tool_choice, model):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(function=SimpleNamespace(**tool_call["function"]))
                                for tool_call in next(responses)
                            ]
                        )
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(agent_module, "OpenAI", FakeOpenAI)

    result = agent_module.AgentOrchestrator().run_task("Process the latest invoice from Acme Corp and update the finance system.")
    assert result.status == "completed"
    assert any(trace.get("source") == "llm" for trace in result.execution_trace)
    assert any(trace.get("failure_retry_decision") == "retry" for trace in result.execution_trace if isinstance(trace, dict))
    assert any(trace.get("verification_decision") == "verified" for trace in result.execution_trace if isinstance(trace, dict))


def test_max_step_protection() -> None:
    original = agent_module.MAX_STEPS
    agent_module.MAX_STEPS = 2
    try:
        result = agent_module.AgentOrchestrator().run_task("Process the latest invoice from Acme Corp and update the finance system.")
        assert result.status == "failed"
        assert any(entry.get("source") == "guardrail" for entry in result.execution_trace)
    finally:
        agent_module.MAX_STEPS = original
