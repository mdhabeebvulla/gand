# Architecture Decisions

## 1. Why JSON + Markdown (not YAML)

| Problem with YAML | How JSON + MD solves it |
|---|---|
| Indentation breaks rules silently | JSON uses explicit brackets |
| Special chars `:{}#` need escaping | JSON auto-escapes strings |
| Multi-line text fragile | Messages live in Markdown files |
| LLMs parse YAML ~70% accurately | LLMs parse JSON ~95% accurately |

## 2. AI Boundary

```
SAFE: AI extracts member context from natural language
       ↓
DETERMINISTIC: Rule engine evaluates JSON conditions
       ↓
SAFE: Message resolver renders Markdown template
```

AI is NEVER used for rule evaluation. This is critical for:
- Regulatory compliance (auditable, reproducible decisions)
- Testing (deterministic input → deterministic output)
- Debugging (exact match traceability)

## 3. Data Flow

```
User Message → OpenAI (NLP extraction) → Structured Context
     → Data Source Resolver (API lookups) → Data Source Results
          → Rule Engine (deterministic) → Matching Rule
               → Message Resolver (Markdown template) → Response
```

## 4. File Organization

- `rules/ga_rules.json` — Business logic (developers + tech BAs)
- `messages/*.md` — Display messages (business analysts)
- `engine/` — Core Python code (developers)
- `api/` — HTTP endpoints (developers)

Business analysts only need to edit Markdown files. No Python/JSON knowledge required.

## 5. Hot Reload

`POST /api/reload` reloads rules + messages from disk without restarting the server.
This enables:
- Edit a .md file → reload → changes are live
- Edit rules.json → reload → new logic active
- No deployment needed for message changes

## 6. Bitbucket Integration

- `bitbucket-pipelines.yml` runs tests on every push
- Rule JSON validation ensures no broken rules reach production
- Message count validation ensures no templates are accidentally deleted
