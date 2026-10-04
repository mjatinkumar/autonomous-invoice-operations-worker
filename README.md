# Autonomous Invoice Operations Worker

## Problem
Manual invoice operations are repetitive, error-prone, and slow. A common finance workflow is: find the most recent invoice for a vendor, read the key values, update the system of record, and independently confirm that the update is correct. This work tends to be mechanical, but it still needs careful verification to avoid incorrect or missing updates.

## Solution
This prototype demonstrates a small autonomous worker that receives a goal, chooses tools dynamically, executes the workflow, handles temporary failures, and verifies the final record before reporting success. It is intentionally narrow: it works with a controlled invoice and finance dataset rather than arbitrary enterprise systems.

## Architecture

User
 ↓
FastAPI
 ↓
Agent Orchestrator
 ↓
┌──────────────────────────────┐
│        Decision Loop         │
│                              │
│  Observe current state       │
│          ↓                   │
│  LLM chooses next tool       │
│          ↓                   │
│  Execute tool                │
│          ↓                   │
│  Record observation          │
│          ↓                   │
│  Retry / continue / verify   │
│          │                   │
│          └───────↩───────────┘
└──────────────────────────────┘
 ↓
Evidence / Final Result

Available Tools
├── search_invoices
├── get_invoice
├── update_finance_record
└── verify_finance_record

## What Is Actually Autonomous?
The worker is intentionally simple but genuinely autonomous within a bounded environment:

- the LLM chooses the next tool based on the current goal and tool results
- tool results influence the next action rather than a hard-coded script
- the worker interprets retryable failures and decides whether to retry
- the final state is checked independently before success is reported
- the task loop includes a step limit so it cannot spin forever

## What Is Hard-Coded?
This is a prototype, so the following are intentionally fixed:

- the available tools are configured by the application
- the database schema is fixed and local to SQLite
- retry boundaries and maximum execution steps are configured by the application
- the finance environment is a controlled simulated system
- it does not discover arbitrary enterprise applications or external APIs
- when `OPENAI_API_KEY` is not set, the application uses a deterministic local demo fallback so the workflow remains testable without external services

## Reliability
Reliability is handled in a few practical ways:

- tool errors are captured and recorded in the execution trace
- when an OpenAI key is configured, the LLM-driven loop decides whether a retry is appropriate based on the current tool result and task state
- when no OpenAI key is configured, the application falls back to a deterministic local demo path for testability and repeatability
- the maximum number of steps prevents infinite loops
- task state persists during one execution for auditing and verification
- verification compares expected invoice values against the actual finance record before reporting success

## Setup
Use the exact commands below from the project root.

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python seed.py
uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python seed.py
uvicorn app.main:app --reload
```

## Environment Variables
Create a local `.env` file with the following values:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
REQUIRE_APPROVAL=false
DB_PATH=./invoices.db
```

Never commit secrets or API keys.

## Demo
The demo request is:

```json
{ "goal": "Process the latest invoice from Acme Corp and update the finance system." }
```

Call the API with:

```bash
curl -X POST http://127.0.0.1:8000/task \
  -H "Content-Type: application/json" \
  -d '{"goal":"Process the latest invoice from Acme Corp and update the finance system."}'
```

In the demo scenario, the worker searches invoices, identifies the newest Acme Corp invoice, updates the finance system, encounters the simulated temporary failure, recovers, and independently verifies the final record.

## Limitations
This is a controlled simulated finance environment. It is not yet a general enterprise automation platform and does not operate arbitrary third-party systems or browse the web. The architecture does recognize the need for human approval on consequential actions, but this prototype uses a lightweight boundary rather than a full multi-step approval UI.

## Design Decisions
This project intentionally avoids unnecessary infrastructure:

- no multi-agent architecture
- no RAG or vector database layer
- no Redis, Celery, or Kubernetes deployment model
- no complex frontend
- no broad enterprise integration framework

The aim is to keep the workflow understandable, testable, and easy to reason about.

## AI Usage
This project was developed with AI assistance for architecture, reasoning, debugging, and review.

- ChatGPT was used for architecture, reasoning, and debugging/review.
- Cline was also used for implementation support and review.

## Future Work
Potential next steps include:

- stronger permission and approval model
- human approval UI
- browser or computer-use workflows
- persistent memory and task history
- background execution
- evaluation dataset and benchmark coverage
- richer failure taxonomy and observability
- broader enterprise workflows beyond invoice processing

## GitHub
This repository is kept intentionally clean and minimal.

- `.gitignore` is included
- `.env.example` is included
- `requirements.txt` is included
- `.env` is never committed
- the runtime-generated SQLite database and local virtual environment are excluded from version control

## Final Submission Note
This repository is structured as a narrow, testable prototype for the CentrAlign AI Engineering Intern assignment. It keeps the scope intentionally bounded to the invoice-processing workflow, the simulated system failure, verification discipline, and a simple FastAPI API. The implementation is designed to be understandable and reviewable instead of making claims about broad enterprise autonomy.

## Code Quality
The implementation chooses simple functions, clear naming, type hints, and small modules. The structure is kept readable so the core agent loop, tooling, and verification path are easy to follow without unnecessary abstractions.

## Safety and Approval Boundary
Finance updates are consequential actions. The code includes an approval gate via the `REQUIRE_APPROVAL` environment variable, and the design assumes a human approval boundary should exist before a real production update. The demo keeps approval off by default so the end-to-end flow can run cleanly in a controlled environment.
