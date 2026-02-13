# G&A Rules Engine POC

**Grievance & Appeals Rules Engine** — A FastAPI + OpenAI powered chatbot that evaluates member context against business rules (JSON) and returns the correct G&A message (Markdown).

## Architecture

```
User Question
      │
      ▼
┌─────────────┐    ┌──────────────┐    ┌───────────────┐
│  FastAPI     │───▶│  OpenAI GPT  │───▶│  Extract      │
│  /api/chat   │    │  (gpt-4o)    │    │  Member       │
│              │    │              │    │  Context      │
└─────────────┘    └──────────────┘    └───────┬───────┘
                                               │
                                               ▼
                                       ┌───────────────┐
                                       │  Rule Engine   │
                                       │  (Deterministic│
                                       │   JSON eval)   │
                                       └───────┬───────┘
                                               │
                                               ▼
                                       ┌───────────────┐
                                       │  Message       │
                                       │  Resolver      │
                                       │  (Markdown)    │
                                       └───────────────┘
```

**KEY PRINCIPLE**: OpenAI extracts structured data from natural language. The **deterministic rule engine** evaluates conditions. AI is NEVER used for rule evaluation.

## Quick Start

### 1. Clone from Bitbucket
```bash
git clone https://bitbucket.org/<your-workspace>/ga-rules-poc.git
cd ga-rules-poc
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Set Environment Variables
```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 5. Run the Server
```bash
uvicorn api.main:app --reload --port 8000
```

### 6. Open the UI
Navigate to: **http://localhost:8000**

API docs at: **http://localhost:8000/docs**

## Project Structure

```
ga_rules_poc/
├── api/
│   ├── __init__.py
│   ├── main.py              ← FastAPI app, routes, CORS
│   ├── chat.py              ← /api/chat endpoint
│   └── models.py            ← Pydantic request/response models
├── engine/
│   ├── __init__.py
│   ├── rule_engine.py       ← Deterministic JSON rule evaluator
│   ├── message_resolver.py  ← Loads & renders Markdown messages
│   ├── context_extractor.py ← OpenAI: natural language → structured context
│   └── data_sources.py      ← Mock data source lookups (FEHBP, GroupDetails)
├── rules/
│   └── ga_rules.json        ← All 22 rules (logic only)
├── messages/
│   ├── FEHBP_MEMBER.md      ← Human-editable message templates
│   ├── FEHBP_BROKER.md
│   └── ... (21 files)
├── static/
│   └── index.html           ← Simple chat UI
├── tests/
│   ├── test_rule_engine.py  ← Unit tests for rule evaluation
│   └── test_scenarios.json  ← Test scenarios per rule
├── docs/
│   └── ARCHITECTURE.md      ← Architecture decisions
├── .env.example
├── .gitignore
├── bitbucket-pipelines.yml  ← CI/CD for Bitbucket
├── requirements.txt
└── README.md
```

## Example Conversation

**User**: "I'm a member in Virginia with an FEHBP account and I want to file a grievance"

**System**:
1. OpenAI extracts: `{ HCCustomerType: "Member", PolicyState: "VA", AccountType: "FEHBP" }`
2. Rule Engine evaluates R001_FEHBP_MEMBER → conditions match
3. Message Resolver loads `FEHBP_MEMBER.md`, fills `{{Policy.PolicyState}}` → "VA"
4. Returns formatted response to user

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send a question, get G&A rule response |
| GET | `/api/rules` | List all active rules |
| GET | `/api/rules/{id}` | Get specific rule details |
| POST | `/api/evaluate` | Evaluate rules with explicit context (no AI) |
| GET | `/api/health` | Health check |

## Testing
```bash
pytest tests/ -v
```

## Bitbucket Setup
See `bitbucket-pipelines.yml` for CI/CD configuration.
