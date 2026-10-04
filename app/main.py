from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.agent import AgentOrchestrator
from app.database import init_db

app = FastAPI(title="Autonomous Invoice Operations Worker")
agent = AgentOrchestrator()


class TaskRequest(BaseModel):
    goal: str


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/task")
def process_task(payload: TaskRequest) -> dict:
    result = agent.run_task(payload.goal)
    return result.model_dump()
