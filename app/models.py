from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class InvoiceRecord(BaseModel):
    id: int
    company: str
    invoice_number: str
    amount: float
    due_date: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class FinanceRecord(BaseModel):
    id: int
    invoice_number: str
    amount: float
    due_date: str
    status: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class TaskState(BaseModel):
    original_goal: str
    status: str = "in_progress"
    current_step: int = 0
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    extracted_invoice: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    retry_count: int = 0
    verification_status: str = "not_started"
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    pending_update: dict[str, Any] | None = None


class TaskResult(BaseModel):
    status: str
    summary: str
    evidence: str
    execution_trace: list[dict[str, Any]]
