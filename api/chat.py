"""
Chat Endpoint
=============
Orchestrates the full flow:
  1. OpenAI extracts structured context from natural language
  2. Data sources resolved (mock for POC)
  3. Deterministic rule engine evaluates conditions
  4. Message resolver renders the Markdown template
"""

import logging
from engine.rule_engine import RuleEngine
from engine.message_resolver import MessageResolver
from engine.context_extractor import ContextExtractor
from engine.data_sources import DataSourceResolver
from api.models import ChatRequest, ChatResponse, EvaluateRequest

logger = logging.getLogger(__name__)

# ─── Fallback message when no rule matches ───
NO_MATCH_MESSAGE = """We were unable to determine the specific grievance and appeal instructions for your situation.

**Please contact Member Services** for assistance with your grievance or appeal request. Have your member ID and policy information ready when you call.

A representative can help determine:
- Whether your request should be submitted verbally or in writing
- The correct mailing address for written submissions
- Any state-specific requirements that may apply
"""


def process_chat(
    request: ChatRequest,
    extractor: ContextExtractor,
    rule_engine: RuleEngine,
    message_resolver: MessageResolver,
    data_resolver: DataSourceResolver,
) -> ChatResponse:
    """
    Process a user's chat message through the full pipeline.

    Flow:
        User message → AI extract → data sources → rule engine → message
    """
    user_msg = request.message
    logger.info(f"Processing chat: {user_msg[:100]}...")

    # ─── Step 1: Extract structured context from natural language ───
    context = extractor.extract(user_msg)
    logger.info(f"Step 1 - Extracted context: {context}")

    # ─── Step 2: Resolve data sources ───
    ds_results = data_resolver.resolve_all(context)
    logger.info(f"Step 2 - Data sources resolved: { {k: bool(v) for k, v in ds_results.items()} }")

    # ─── Step 3: Evaluate rules (DETERMINISTIC — no AI here) ───
    match = rule_engine.evaluate(context, ds_results)
    logger.info(f"Step 3 - Rule match: {match}")

    # ─── Step 4: Resolve message template ───
    if match:
        message_ref = match.get("message_ref", "")
        resolved = message_resolver.resolve(message_ref, context, ds_results)

        if resolved:
            return ChatResponse(
                message=resolved["markdown"],
                message_html=resolved["html"],
                rule_matched=match["rule_id"],
                rule_name=match["name"],
                extracted_context=context,
                data_sources_resolved={ k: bool(v) for k, v in ds_results.items() },
                confidence="high" if match.get("priority", 999) < 50 else "medium",
            )

    # No match
    logger.info("No rule matched — returning fallback message")
    import markdown as md

    return ChatResponse(
        message=NO_MATCH_MESSAGE,
        message_html=md.markdown(NO_MATCH_MESSAGE),
        rule_matched=None,
        rule_name=None,
        extracted_context=context,
        data_sources_resolved={ k: bool(v) for k, v in ds_results.items() },
        confidence="none",
    )


def process_evaluate(
    request: EvaluateRequest,
    rule_engine: RuleEngine,
    message_resolver: MessageResolver,
    data_resolver: DataSourceResolver,
) -> ChatResponse:
    """
    Evaluate rules with explicit context (no AI extraction).
    Useful for testing and integration from other systems.
    """
    context = request.context
    ds_results = data_resolver.resolve_all(context)
    match = rule_engine.evaluate(context, ds_results)

    if match:
        message_ref = match.get("message_ref", "")
        resolved = message_resolver.resolve(message_ref, context, ds_results)

        if resolved:
            return ChatResponse(
                message=resolved["markdown"],
                message_html=resolved["html"],
                rule_matched=match["rule_id"],
                rule_name=match["name"],
                extracted_context=context,
                data_sources_resolved={ k: bool(v) for k, v in ds_results.items() },
                confidence="high",
            )

    import markdown as md

    return ChatResponse(
        message=NO_MATCH_MESSAGE,
        message_html=md.markdown(NO_MATCH_MESSAGE),
        rule_matched=None,
        rule_name=None,
        extracted_context=context,
        data_sources_resolved={ k: bool(v) for k, v in ds_results.items() },
        confidence="none",
    )
