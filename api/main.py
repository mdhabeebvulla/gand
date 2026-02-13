"""
G&A Rules Engine — FastAPI Application
=======================================
Main entry point. Run with:
    uvicorn api.main:app --reload --port 8000
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.models import (
    ChatRequest, ChatResponse, EvaluateRequest,
    HealthResponse, RuleSummary,
)
from api.chat import process_chat, process_evaluate
from api import admin as admin_module
from engine.rule_engine import RuleEngine
from engine.message_resolver import MessageResolver
from engine.context_extractor import ContextExtractor
from engine.data_sources import DataSourceResolver
from engine.bitbucket_client import BitbucketClient

# ─── Load environment variables ───
load_dotenv()

# ─── Logging ───
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Resolve paths relative to project root ───
BASE_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = BASE_DIR / "rules" / "ga_rules.json"
MESSAGES_DIR = BASE_DIR / "messages"
STATIC_DIR = BASE_DIR / "static"

# ─── Initialize components ───
logger.info(f"Base directory: {BASE_DIR}")
logger.info(f"Rules path: {RULES_PATH}")
logger.info(f"Messages dir: {MESSAGES_DIR}")

rule_engine = RuleEngine(str(RULES_PATH))
message_resolver = MessageResolver(str(MESSAGES_DIR))
context_extractor = ContextExtractor(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_MODEL", "gpt-4o"),
)
data_resolver = DataSourceResolver(mode="mock")

# ─── Bitbucket Client ───
bb_client = BitbucketClient(
    workspace=os.getenv("BB_WORKSPACE"),
    repo_slug=os.getenv("BB_REPO_SLUG"),
    username=os.getenv("BB_USERNAME"),
    app_password=os.getenv("BB_APP_PASSWORD"),
    branch=os.getenv("BB_BRANCH", "main"),
)

# ─── Initialize Admin Module ───
admin_module.init(bb_client, rule_engine, message_resolver)

# ─── FastAPI App ───
app = FastAPI(
    title="G&A Rules Engine",
    description=(
        "Grievance & Appeals Rules Engine POC. "
        "Uses OpenAI for natural language understanding and a deterministic "
        "JSON rule engine for rule evaluation."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS (allow frontend) ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Include Admin API routes ───
app.include_router(admin_module.router)


# ═══════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the chat UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return HTMLResponse(content="<h1>G&A Rules Engine</h1><p>Visit /docs for API documentation.</p>")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Serve the admin UI for editing rules and messages."""
    admin_path = STATIC_DIR / "admin.html"
    if admin_path.exists():
        return HTMLResponse(content=admin_path.read_text())
    return HTMLResponse(content="<h1>Admin page not found</h1>")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    🗣️ Chat endpoint — Send a natural language question about G&A.

    **Flow**:
    1. OpenAI extracts member context from your question
    2. Deterministic rule engine evaluates JSON conditions
    3. Matching message template is rendered with real values

    **Example**: "I'm a member in Virginia with an FEHBP account and want to file a grievance"
    """
    try:
        return process_chat(
            request=request,
            extractor=context_extractor,
            rule_engine=rule_engine,
            message_resolver=message_resolver,
            data_resolver=data_resolver,
        )
    except Exception as e:
        logger.exception(f"Chat processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


@app.post("/api/evaluate", response_model=ChatResponse)
async def evaluate(request: EvaluateRequest):
    """
    🔧 Direct evaluation — Pass explicit context (no AI extraction).

    Useful for:
    - Integration testing
    - Calls from other systems
    - Debugging specific rule matches

    **Example body**:
    ```json
    {
        "context": {
            "HCCustomerType": "Member",
            "Policy.PolicyState": "VA",
            "account_type": "FEHBP",
            "has_fehbp_address": true,
            "IsASO": false
        }
    }
    ```
    """
    try:
        return process_evaluate(
            request=request,
            rule_engine=rule_engine,
            message_resolver=message_resolver,
            data_resolver=data_resolver,
        )
    except Exception as e:
        logger.exception(f"Evaluation error: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation error: {str(e)}")


@app.get("/api/rules", response_model=list[RuleSummary])
async def list_rules():
    """📋 List all active rules with metadata."""
    return rule_engine.get_all_rules()


@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str):
    """📋 Get a specific rule by ID."""
    rule = rule_engine.get_rule_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    return rule


@app.post("/api/reload")
async def reload_rules():
    """🔄 Hot-reload rules and messages from disk (no restart needed)."""
    rule_engine.reload()
    message_resolver.reload()
    return {
        "status": "reloaded",
        "rules_count": len(rule_engine.rules),
        "messages_count": len(message_resolver.cache),
    }


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """❤️ Health check."""
    return HealthResponse(
        status="healthy",
        rules_loaded=len(rule_engine.rules),
        messages_loaded=len(message_resolver.cache),
        openai_configured=context_extractor.client is not None,
    )


# ─── Startup/Shutdown ───
@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("G&A Rules Engine POC — Starting")
    logger.info(f"  Rules loaded: {len(rule_engine.rules)}")
    logger.info(f"  Messages loaded: {len(message_resolver.cache)}")
    logger.info(f"  OpenAI configured: {context_extractor.client is not None}")
    logger.info(f"  Bitbucket configured: {bb_client.configured}")
    logger.info(f"  Mode: {data_resolver.mode}")
    logger.info(f"  Chat UI:  http://localhost:8000/")
    logger.info(f"  Admin UI: http://localhost:8000/admin")
    logger.info(f"  API Docs: http://localhost:8000/docs")
    logger.info("=" * 60)
