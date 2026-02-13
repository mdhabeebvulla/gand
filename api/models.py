"""Pydantic models for API request/response schemas."""

from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """User sends a natural language question about G&A."""
    message: str = Field(
        ...,
        description="User's question about grievance/appeal",
        min_length=1,
        max_length=2000,
        json_schema_extra={"examples": [
            "I'm a member in Virginia with an FEHBP account and want to file a grievance"
        ]},
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session ID for conversation tracking",
    )


class ChatResponse(BaseModel):
    """Response with matched rule and rendered message."""
    message: str = Field(description="Human-readable response message (Markdown)")
    message_html: str = Field(description="HTML-rendered message")
    rule_matched: Optional[str] = Field(description="ID of the matched rule")
    rule_name: Optional[str] = Field(description="Name of the matched rule")
    extracted_context: dict = Field(description="Context extracted from user's question")
    data_sources_resolved: dict = Field(description="Data source results used")
    confidence: str = Field(description="Match confidence: high, medium, low, none")


class EvaluateRequest(BaseModel):
    """Directly evaluate rules with explicit context (no AI extraction)."""
    context: dict = Field(
        ...,
        description="Member context fields",
        json_schema_extra={"examples": [{
            "HCCustomerType": "Member",
            "Policy.PolicyState": "VA",
            "account_type": "FEHBP",
            "has_fehbp_address": True,
            "IsASO": False,
        }]},
    )


class RuleSummary(BaseModel):
    """Summary of a rule for listing."""
    id: str
    name: str
    priority: int
    active: bool
    tags: list[str]
    message_ref: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    rules_loaded: int
    messages_loaded: int
    openai_configured: bool
