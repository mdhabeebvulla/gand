"""
Admin API Routes
================
CRUD endpoints for rules and messages, with Bitbucket commit integration.

Endpoints:
  GET    /admin/api/rules              → list all rules (summary)
  GET    /admin/api/rules/{id}         → get single rule JSON
  PUT    /admin/api/rules/{id}         → update a rule + commit to Bitbucket
  POST   /admin/api/rules/{id}/toggle  → activate/deactivate
  GET    /admin/api/messages            → list all message files
  GET    /admin/api/messages/{name}     → get message content
  PUT    /admin/api/messages/{name}     → update message + commit
  POST   /admin/api/messages            → create new message file
  GET    /admin/api/history             → recent commits from Bitbucket
  POST   /admin/api/validate-rules      → validate rules JSON without saving
  POST   /admin/api/sync-from-bb        → pull latest from Bitbucket + reload
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.bitbucket_client import BitbucketClient
from engine.rule_engine import RuleEngine
from engine.message_resolver import MessageResolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["admin"])

# These will be injected from main.py
bb_client: Optional[BitbucketClient] = None
rule_engine: Optional[RuleEngine] = None
msg_resolver: Optional[MessageResolver] = None

RULES_FILE_PATH = "rules/ga_rules.json"
MESSAGES_DIR_PATH = "messages"


def init(bb: BitbucketClient, engine: RuleEngine, resolver: MessageResolver):
    """Inject dependencies from main app."""
    global bb_client, rule_engine, msg_resolver
    bb_client, rule_engine, msg_resolver = bb, engine, resolver


# ═══════════════════════════════════════════
# Models
# ═══════════════════════════════════════════

class RuleUpdate(BaseModel):
    rule_json: dict = Field(..., description="Complete rule object")
    commit_message: str = Field(default="", description="Commit message for Bitbucket")
    author: str = Field(default="G&A Admin", description="Author name")


class RuleToggle(BaseModel):
    active: bool
    commit_message: str = Field(default="")


class MessageUpdate(BaseModel):
    content: str = Field(..., description="Markdown content")
    commit_message: str = Field(default="", description="Commit message")
    author: str = Field(default="G&A Admin")


class MessageCreate(BaseModel):
    name: str = Field(..., description="Filename without .md extension", pattern=r"^[A-Z0-9_]+$")
    content: str = Field(..., description="Markdown content")
    commit_message: str = Field(default="")
    author: str = Field(default="G&A Admin")


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    rule_count: int


# ═══════════════════════════════════════════
# RULES endpoints
# ═══════════════════════════════════════════

@router.get("/rules")
async def list_rules():
    """List all rules with metadata."""
    rules = rule_engine.get_all_rules()
    return {
        "rules": rules,
        "total": len(rules),
        "bitbucket_configured": bb_client.configured,
    }


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str):
    """Get a single rule's full JSON."""
    rule = rule_engine.get_rule_by_id(rule_id)
    if not rule:
        raise HTTPException(404, f"Rule not found: {rule_id}")
    return rule


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, update: RuleUpdate):
    """
    Update a rule and commit to Bitbucket.

    1. Loads the full rules JSON
    2. Replaces the specific rule
    3. Validates the result
    4. Commits to Bitbucket (or saves locally)
    5. Reloads the rule engine
    """
    # Load current rules
    raw = await bb_client.get_file(RULES_FILE_PATH)
    if not raw:
        raise HTTPException(500, "Could not load rules file")

    try:
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"Rules file has invalid JSON: {e}")

    # Find and replace the rule
    rules_list = config.get("rules", [])
    found = False
    for i, r in enumerate(rules_list):
        if r.get("id") == rule_id:
            rules_list[i] = update.rule_json
            found = True
            break

    if not found:
        raise HTTPException(404, f"Rule {rule_id} not found in rules file")

    config["rules"] = rules_list

    # Validate
    errors = _validate_rules_config(config)
    if errors:
        raise HTTPException(400, f"Validation failed: {'; '.join(errors)}")

    # Commit
    new_json = json.dumps(config, indent=2, ensure_ascii=False)
    msg = update.commit_message or f"Update rule {rule_id}"
    result = await bb_client.commit_file(RULES_FILE_PATH, new_json, msg, update.author)

    if not result["success"]:
        raise HTTPException(500, f"Commit failed: {result['message']}")

    # Reload engine
    rule_engine.reload()

    return {
        "success": True,
        "commit": result["commit_hash"],
        "message": result["message"],
        "rule_id": rule_id,
    }


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, toggle: RuleToggle):
    """Activate or deactivate a rule."""
    raw = await bb_client.get_file(RULES_FILE_PATH)
    if not raw:
        raise HTTPException(500, "Could not load rules file")

    config = json.loads(raw)
    rules_list = config.get("rules", [])

    found = False
    for r in rules_list:
        if r.get("id") == rule_id:
            r["active"] = toggle.active
            found = True
            break

    if not found:
        raise HTTPException(404, f"Rule {rule_id} not found")

    new_json = json.dumps(config, indent=2, ensure_ascii=False)
    msg = toggle.commit_message or f"{'Activate' if toggle.active else 'Deactivate'} rule {rule_id}"
    result = await bb_client.commit_file(RULES_FILE_PATH, new_json, msg)

    if result["success"]:
        rule_engine.reload()

    return {"success": result["success"], "active": toggle.active, "message": result["message"]}


# ═══════════════════════════════════════════
# MESSAGES endpoints
# ═══════════════════════════════════════════

@router.get("/messages")
async def list_messages():
    """List all message template files."""
    templates = msg_resolver.list_templates()
    result = []
    for name in templates:
        content = msg_resolver.cache.get(name, "")
        # Count placeholders
        import re
        placeholders = re.findall(r"\{\{(.+?)\}\}", content)
        result.append({
            "name": name,
            "path": f"{MESSAGES_DIR_PATH}/{name}.md",
            "length": len(content),
            "placeholders": placeholders,
            "preview": content[:120] + ("..." if len(content) > 120 else ""),
        })
    return {"messages": result, "total": len(result)}


@router.get("/messages/{name}")
async def get_message(name: str):
    """Get a message template's content."""
    # Try from Bitbucket first, then local cache
    file_path = f"{MESSAGES_DIR_PATH}/{name}.md"
    content = await bb_client.get_file(file_path)

    if content is None:
        # Fall back to cached version
        body = msg_resolver.cache.get(name)
        if body is None:
            raise HTTPException(404, f"Message not found: {name}")
        content = body

    # Parse frontmatter
    frontmatter = {}
    body = content
    parts = content.split("---")
    if len(parts) >= 3:
        import re
        fm_text = parts[1].strip()
        for line in fm_text.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                frontmatter[key.strip()] = val.strip()
        body = "---".join(parts[2:]).strip()

    return {
        "name": name,
        "path": file_path,
        "raw_content": content,
        "body": body,
        "frontmatter": frontmatter,
    }


@router.put("/messages/{name}")
async def update_message(name: str, update: MessageUpdate):
    """Update a message and commit to Bitbucket."""
    file_path = f"{MESSAGES_DIR_PATH}/{name}.md"
    msg = update.commit_message or f"Update message: {name}"
    result = await bb_client.commit_file(file_path, update.content, msg, update.author)

    if not result["success"]:
        raise HTTPException(500, f"Commit failed: {result['message']}")

    # Reload messages
    msg_resolver.reload()

    return {"success": True, "commit": result["commit_hash"], "message": result["message"]}


@router.post("/messages")
async def create_message(create: MessageCreate):
    """Create a new message file."""
    file_path = f"{MESSAGES_DIR_PATH}/{create.name}.md"

    # Check doesn't already exist
    existing = await bb_client.get_file(file_path)
    if existing:
        raise HTTPException(409, f"Message already exists: {create.name}")

    msg = create.commit_message or f"Create new message: {create.name}"
    result = await bb_client.commit_file(file_path, create.content, msg, create.author)

    if result["success"]:
        msg_resolver.reload()

    return {"success": result["success"], "commit": result["commit_hash"], "message": result["message"]}


# ═══════════════════════════════════════════
# HISTORY & VALIDATION
# ═══════════════════════════════════════════

@router.get("/history")
async def get_history(file_path: Optional[str] = None, limit: int = 20):
    """Get commit history from Bitbucket."""
    commits = await bb_client.get_commits(file_path=file_path, limit=limit)
    return {"commits": commits, "total": len(commits)}


@router.post("/validate-rules")
async def validate_rules(body: dict):
    """Validate rules JSON without saving."""
    rules_json = body.get("rules_json", "")
    try:
        if isinstance(rules_json, str):
            config = json.loads(rules_json)
        else:
            config = rules_json
    except json.JSONDecodeError as e:
        return ValidationResult(valid=False, errors=[f"Invalid JSON: {e}"], warnings=[], rule_count=0)

    errors = _validate_rules_config(config)
    warnings = _get_warnings(config)
    rule_count = len(config.get("rules", []))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        rule_count=rule_count,
    )


@router.post("/sync-from-bb")
async def sync_from_bitbucket():
    """Pull latest from Bitbucket and reload engine."""
    if not bb_client.configured:
        return {"success": True, "message": "Local mode — reloaded from disk"}

    # Fetch rules
    rules_content = await bb_client.get_file(RULES_FILE_PATH)
    if rules_content:
        rules_path = bb_client._get_base_dir() / RULES_FILE_PATH
        rules_path.write_text(rules_content, encoding="utf-8")

    # Fetch messages
    files = await bb_client.list_files(MESSAGES_DIR_PATH)
    for f in files:
        content = await bb_client.get_file(f["path"])
        if content:
            local_path = bb_client._get_base_dir() / f["path"]
            local_path.write_text(content, encoding="utf-8")

    # Reload
    rule_engine.reload()
    msg_resolver.reload()

    return {
        "success": True,
        "message": f"Synced from Bitbucket. Rules: {len(rule_engine.rules)}, Messages: {len(msg_resolver.cache)}",
    }


@router.get("/config")
async def get_config():
    """Get admin configuration status."""
    return {
        "bitbucket": {
            "configured": bb_client.configured,
            "workspace": bb_client.workspace,
            "repo": bb_client.repo_slug,
            "branch": bb_client.branch,
        },
        "engine": {
            "rules_loaded": len(rule_engine.rules),
            "messages_loaded": len(msg_resolver.cache),
        },
    }


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

def _validate_rules_config(config: dict) -> list[str]:
    """Validate a rules config dict. Returns list of errors."""
    errors = []

    if not isinstance(config, dict):
        return ["Root must be a JSON object"]

    rules = config.get("rules")
    if not isinstance(rules, list):
        errors.append("'rules' must be an array")
        return errors

    ids = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"Rule #{i} is not an object")
            continue

        rid = rule.get("id")
        if not rid:
            errors.append(f"Rule #{i} missing 'id'")
        elif rid in ids:
            errors.append(f"Duplicate rule id: {rid}")
        else:
            ids.add(rid)

        if "conditions" not in rule:
            errors.append(f"Rule {rid}: missing 'conditions'")

        if "message_ref" not in rule:
            errors.append(f"Rule {rid}: missing 'message_ref'")

        if "priority" not in rule:
            errors.append(f"Rule {rid}: missing 'priority'")

    return errors


def _get_warnings(config: dict) -> list[str]:
    """Non-critical warnings."""
    warnings = []
    rules = config.get("rules", [])

    # Check for missing message templates
    for rule in rules:
        ref = rule.get("message_ref", "")
        if ref and ref not in msg_resolver.cache:
            warnings.append(f"Rule {rule.get('id')}: message_ref '{ref}' has no matching .md file")

    # Check for duplicate priorities
    priorities = [r.get("priority") for r in rules if r.get("priority") is not None]
    seen = set()
    for p in priorities:
        if p in seen:
            warnings.append(f"Duplicate priority: {p} (rules may have unpredictable order)")
        seen.add(p)

    return warnings
