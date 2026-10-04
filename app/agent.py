from __future__ import annotations

import logging
import os
import re
from typing import Any

from openai import OpenAI

from app.models import TaskResult, TaskState
from app.tools import (
    get_invoice,
    latest_invoice_for_company,
    search_invoices,
    update_finance_record,
    verify_finance_record,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MAX_STEPS = 10
MAX_RETRIES = 2

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search_invoices",
            "description": "Search invoice records by company name.",
            "parameters": {
                "type": "object",
                "properties": {"company": {"type": "string"}},
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice",
            "description": "Retrieve the full invoice record by invoice id.",
            "parameters": {
                "type": "object",
                "properties": {"invoice_id": {"type": ["string", "integer"]}},
                "required": ["invoice_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_finance_record",
            "description": "Update the finance system record for an invoice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string"},
                    "amount": {"type": "number"},
                    "due_date": {"type": "string"},
                },
                "required": ["invoice_number", "amount", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_finance_record",
            "description": "Independently check the database record for a finance update.",
            "parameters": {
                "type": "object",
                "properties": {"invoice_number": {"type": "string"}},
                "required": ["invoice_number"],
            },
        },
    },
]


class AgentOrchestrator:
    def _extract_company(self, goal: str) -> str:
        match = re.search(r"from\s+(.+?)(?:\s+and\s+|\s+to\s+|\s+for\s+|$)", goal, flags=re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            if company:
                return company
        return "Acme Corp"

    def _build_llm_messages(self, goal: str, state: TaskState) -> list[dict[str, str]]:
        previous_tool_results = state.tool_results[-3:] if state.tool_results else []
        return [
            {
                "role": "system",
                "content": (
                    "You are a cautious invoice operations worker. "
                    "Use the supplied tools to satisfy the user's goal. "
                    "The current state and previous tool results are your primary decision inputs. "
                    "You must decide the next tool based on the goal, current state, previous observations, and available tools."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original goal: {goal}\n"
                    f"Current state: {state.model_dump_json(indent=2)}\n"
                    f"Previous tool results: {previous_tool_results}\n"
                    f"Available tools: {', '.join(tool['function']['name'] for tool in TOOL_DEFS)}"
                ),
            },
        ]

    def _choose_with_llm(self, goal: str, state: TaskState) -> tuple[str | None, str | dict[str, Any] | None]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None, None

        try:
            client = OpenAI(api_key=api_key)
            completion = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=self._build_llm_messages(goal, state),
                tools=TOOL_DEFS,
                tool_choice="auto",
            )
            tool_call = completion.choices[0].message.tool_calls[0] if completion.choices[0].message.tool_calls else None
            if tool_call is None:
                return None, None

            name = tool_call.function.name
            arguments = tool_call.function.arguments
            parsed = {}
            try:
                parsed = eval(arguments, {}, {}) if isinstance(arguments, str) else arguments
            except Exception:
                parsed = {}
            return name, parsed
        except Exception as exc:  # pragma: no cover - tool-calling fallback
            logger.warning("OpenAI tool selection failed; using deterministic local fallback: %s", exc)
            return None, None

    def _choose_fallback_local_demo(self, goal: str, state: TaskState) -> tuple[str | None, dict[str, Any]]:
        """Deterministic local demo fallback only. This is not autonomous decision-making."""
        last_result = state.tool_results[-1]["result"] if state.tool_results else {}
        last_tool = state.tool_calls[-1]["tool"] if state.tool_calls else None

        if state.current_step == 1:
            company = self._extract_company(goal)
            return "search_invoices", {"company": company}

        if state.extracted_invoice is None and last_result.get("success") and last_result.get("invoices"):
            latest = max(last_result["invoices"], key=lambda invoice: invoice["created_at"])
            return "get_invoice", {"invoice_id": latest["id"]}

        if state.extracted_invoice is not None and state.pending_update is not None and last_tool != "update_finance_record":
            invoice = state.extracted_invoice
            return "update_finance_record", {
                "invoice_number": invoice["invoice_number"],
                "amount": float(invoice["amount"]),
                "due_date": invoice["due_date"],
            }

        if (
            last_result.get("success") is False
            and last_result.get("retryable")
            and state.retry_count < MAX_RETRIES
            and state.pending_update is not None
        ):
            return "update_finance_record", state.pending_update

        if state.pending_update is not None and last_tool == "update_finance_record" and state.verification_status in {"not_started", "pending"}:
            return "verify_finance_record", {"invoice_number": state.pending_update["invoice_number"]}

        return None, {}

    def _execute_tool(self, tool_name: str | None, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if not tool_name:
            return {"success": False, "error": "No valid tool selected"}

        registry = {
            "search_invoices": lambda: search_invoices(**arguments or {}),
            "get_invoice": lambda: get_invoice(**arguments or {}),
            "update_finance_record": lambda: update_finance_record(**arguments or {}),
            "verify_finance_record": lambda: verify_finance_record(**arguments or {}),
        }
        handler = registry.get(tool_name)
        if handler is None:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        return handler()

    def _summarize_observation(self, tool_name: str, tool_result: dict[str, Any]) -> str:
        if tool_result.get("success") is False:
            return tool_result.get("error", f"{tool_name} failed")
        if tool_name == "search_invoices":
            return f"{tool_result.get('count', 0)} invoice(s) found for {tool_result.get('company')}"
        if tool_name == "get_invoice":
            invoice = tool_result.get("invoice") or {}
            return f"Invoice {invoice.get('invoice_number')} retrieved"
        if tool_name == "update_finance_record":
            finance_record = tool_result.get("finance_record") or {}
            return f"Finance update status: {finance_record.get('status', tool_result.get('status', 'unknown'))}"
        if tool_name == "verify_finance_record":
            record = tool_result.get("record") or {}
            return f"Verified finance record for {record.get('invoice_number', 'unknown')}"
        return "Tool completed successfully"

    def _update_state_after_tool(self, state: TaskState, tool_name: str, tool_result: dict[str, Any]) -> None:
        if tool_name == "search_invoices" and tool_result.get("success"):
            state.tool_results[-1]["tool"] = tool_name
            if tool_result.get("invoices"):
                latest = max(tool_result["invoices"], key=lambda invoice: invoice["created_at"])
                state.extracted_invoice = None
                state.pending_update = None
                if latest.get("invoice_number"):
                    logger.info("Latest invoice candidate: %s (%s)", latest["invoice_number"], latest["created_at"])

        elif tool_name == "get_invoice" and tool_result.get("success"):
            state.extracted_invoice = tool_result.get("invoice")
            state.pending_update = {
                "invoice_number": tool_result["invoice"]["invoice_number"],
                "amount": float(tool_result["invoice"]["amount"]),
                "due_date": tool_result["invoice"]["due_date"],
            }

        elif tool_name == "update_finance_record":
            if tool_result.get("success"):
                state.pending_update = state.pending_update or {}
                state.verification_status = "pending"
            else:
                state.errors.append(tool_result.get("error", "Tool failed"))
                if tool_result.get("retryable"):
                    state.retry_count += 1

        elif tool_name == "verify_finance_record" and tool_result.get("success"):
            actual = tool_result.get("record") or {}
            expected = state.extracted_invoice or {}
            expected_number = expected.get("invoice_number")
            expected_amount = float(expected.get("amount", 0.0))
            expected_due_date = expected.get("due_date")
            actual_matches = (
                actual.get("invoice_number") == expected_number
                and float(actual.get("amount", 0.0)) == expected_amount
                and actual.get("due_date") == expected_due_date
            )
            state.verification_status = "verified" if actual_matches else "failed"
            state.status = "completed" if actual_matches else "failed"
            logger.info("Verification matches expected values: %s", actual_matches)

        if tool_result.get("success") is False and tool_result.get("retryable"):
            logger.warning("Retryable error recorded: %s", tool_result.get("error"))

    def run_task(self, goal: str) -> TaskResult:
        state = TaskState(original_goal=goal)
        logger.info("Starting task: %s", goal)

        while state.status == "in_progress" and state.current_step < MAX_STEPS:
            state.current_step += 1
            decision = None
            tool_name = None
            arguments: dict[str, Any] | None = {}
            decision_source = "llm"

            llm_choice = self._choose_with_llm(goal, state)
            if llm_choice[0] is not None:
                tool_name, arguments = llm_choice
                decision = f"LLM selected {tool_name} with tool_choice='auto' based on current state and observations."
            else:
                decision_source = "fallback_local_demo"
                tool_name, arguments = self._choose_fallback_local_demo(goal, state)
                decision = (
                    f"Fallback local demo planner selected {tool_name} because the LLM path was unavailable."
                    if tool_name
                    else "No further action needed; the goal has been satisfied or the loop has ended."
                )

            if tool_name is None:
                state.status = "completed"
                logger.info("Task reached a terminal state without another tool call.")
                break

            logger.info("STEP %s | Source: %s | Decision: %s | Tool: %s | Args: %s", state.current_step, decision_source, decision, tool_name, arguments)
            result = self._execute_tool(tool_name, arguments)
            logger.info("STEP %s | Result: %s", state.current_step, result)

            state.tool_calls.append({"step": state.current_step, "tool": tool_name, "arguments": arguments})
            state.tool_results.append({"step": state.current_step, "result": result})
            observation = self._summarize_observation(tool_name, result)
            failure_retry_decision = None
            verification_decision = None
            if result.get("success") is False and result.get("retryable"):
                failure_retry_decision = "retry" if state.retry_count < MAX_RETRIES else "stop"
            if tool_name == "verify_finance_record":
                verification_decision = "verified" if result.get("success") and result.get("record") else "failed"
            if tool_name == "update_finance_record" and result.get("success"):
                verification_decision = "pending_verification"

            state.execution_trace.append(
                {
                    "step": state.current_step,
                    "source": decision_source,
                    "decision": decision,
                    "selected_tool": tool_name,
                    "tool_arguments": arguments,
                    "observation": observation,
                    "tool_result": result,
                    "failure_retry_decision": failure_retry_decision,
                    "verification_decision": verification_decision,
                }
            )

            self._update_state_after_tool(state, tool_name, result)

            if state.status == "completed":
                state.execution_trace.append(
                    {
                        "step": "final",
                        "source": "verifier",
                        "final_outcome": "completed",
                        "verification_status": state.verification_status,
                        "observation": "Final outcome set only after independent verification matched expected values.",
                    }
                )
                break

            if state.current_step >= MAX_STEPS:
                state.status = "failed"
                state.errors.append("Maximum step limit reached before the task could be verified.")
                state.execution_trace.append({
                    "step": "final",
                    "source": "guardrail",
                    "final_outcome": "failed",
                    "observation": "Maximum steps reached; task aborted before verification completed.",
                })
                break

            if state.retry_count >= MAX_RETRIES and state.tool_results and state.tool_results[-1]["result"].get("retryable"):
                state.status = "failed"
                state.errors.append("Retry limit reached before successful finance update.")
                state.execution_trace.append({
                    "step": "final",
                    "source": "guardrail",
                    "final_outcome": "failed",
                    "observation": "Retry budget exhausted; task aborted before successful completion.",
                })
                break

        final_summary = "Task completed successfully and verified against the finance record."
        evidence = "Verified the finance record against the expected invoice values."
        if state.status != "completed":
            final_summary = "Task did not complete successfully."
            evidence = "; ".join(state.errors) if state.errors else "No independent verification was completed."

        if state.extracted_invoice and state.pending_update and state.status == "completed":
            expected = state.extracted_invoice
            evidence = (
                f"Expected invoice {expected['invoice_number']} for {expected['company']} at amount {expected['amount']} due {expected['due_date']}. "
                f"Finance record matched after verification."
            )

        return TaskResult(
            status=state.status,
            summary=final_summary,
            evidence=evidence,
            execution_trace=state.execution_trace,
        )
