"""
Context Extractor (OpenAI)
==========================
Uses OpenAI GPT to extract structured member context from natural language questions.

IMPORTANT: AI is ONLY used here for NLP extraction.
           Rule evaluation is ALWAYS deterministic (rule_engine.py).
"""

import json
import logging
import os
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ─── System prompt for context extraction ───
EXTRACTION_PROMPT = """You are a healthcare Grievance & Appeals (G&A) context extractor.

Given a user's question about filing a grievance or appeal, extract structured member information.

Return ONLY a valid JSON object with these fields (include only fields that can be inferred):

{
  "HCCustomerType": "Member" | "Broker" | "Provider",
  "Policy.PolicyState": "two-letter state code, e.g. VA, CA, NV",
  "Policy.MBUCode": "IND" | "LG" | "NATL" | "SG",
  "Policy.BusinessUnit": "National" | "Local" | "",
  "Policy.GroupNumber": "group number if mentioned",
  "Policy.FinCompanyCode": "company code if mentioned",
  "Policy.FinCompanyName": "company name if mentioned",
  "Policy.AntmCompanyCodeName": "Anthem company code name if mentioned",
  "Policy.CoverageTypeCode": "MED" | "DEN" | "VIS",
  "Policy.ExchangeIndCode": "Y" | "N" | "NA",
  "Policy.SourceSystemId": "source system if mentioned",
  "IsASO": true | false,
  "IsVAExpedited": true | false,
  "IsVerbalGandAAllowed": "Yes" | "No",
  "IsGandAInWritingAllowed": "Yes" | "No",
  "ParentName": "Provider" | "Member" | "Broker",
  "account_type": "FEHBP" | "SHBP" | "National" | "Individual" | "Exchange",
  "has_fehbp_address": true | false,
  "funding_type": "Fully Insured" | "ASO" | "Self-Funded",
  "is_written_request": true | false,
  "has_attachment": true | false,
  "request_type": "grievance" | "appeal" | "both"
}

Rules for extraction:
- "FEHBP" or "Federal Employee" → account_type = "FEHBP", has_fehbp_address = true
- "SHBP" or "State Health Benefit" → account_type = "SHBP"
- "National account" → Policy.BusinessUnit = "National"
- "Individual" or "exchange" or "marketplace" → Policy.MBUCode = "IND"
- "expedited" + state is VA → IsVAExpedited = true
- "ASO" or "self-funded" or "administrative services" → IsASO = true
- "fully insured" → funding_type = "Fully Insured", IsASO = false
- If user says "verbal" → IsVerbalGandAAllowed could be relevant
- If user says "in writing" or "written" → is_written_request = true
- Default HCCustomerType to "Member" unless stated otherwise
- Default IsASO to false unless stated otherwise

Return ONLY the JSON object. No explanation, no markdown backticks."""


class ContextExtractor:
    """Extract structured member context from natural language using OpenAI."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

        if not self.api_key:
            logger.warning("No OpenAI API key configured — context extraction will use fallback")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"OpenAI context extractor initialized (model: {self.model})")

    def extract(self, user_message: str) -> dict:
        """
        Extract member context from a natural language message.

        Args:
            user_message: User's question about G&A, e.g.
                "I'm a member in Virginia with an FEHBP account..."

        Returns:
            Structured context dict for the rule engine.
        """
        if not self.client:
            logger.info("No OpenAI client — using keyword fallback extraction")
            return self._fallback_extract(user_message)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,  # Deterministic extraction
                max_tokens=500,
            )

            raw = response.choices[0].message.content.strip()

            # Strip markdown backticks if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            context = json.loads(raw)
            logger.info(f"Extracted context: {json.dumps(context, indent=2)}")
            return context

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            return self._fallback_extract(user_message)
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            return self._fallback_extract(user_message)

    def _fallback_extract(self, msg: str) -> dict:
        """
        Simple keyword-based extraction when OpenAI is unavailable.
        Used for testing without an API key.
        """
        msg_lower = msg.lower()
        context = {}

        # Customer type
        if "broker" in msg_lower:
            context["HCCustomerType"] = "Broker"
        elif "provider" in msg_lower:
            context["HCCustomerType"] = "Provider"
            context["ParentName"] = "Provider"
        else:
            context["HCCustomerType"] = "Member"

        # State detection
        state_map = {
            "virginia": "VA", "california": "CA", "nevada": "NV",
            "georgia": "GA", "missouri": "MO", "colorado": "CO",
            "wisconsin": "WI", "new york": "NY", "texas": "TX",
            "florida": "FL", "ohio": "OH", "pennsylvania": "PA",
        }
        for name, code in state_map.items():
            if name in msg_lower or f" {code.lower()} " in f" {msg_lower} ":
                context["Policy.PolicyState"] = code
                break

        # Account type
        if "fehbp" in msg_lower or "federal employee" in msg_lower:
            context["account_type"] = "FEHBP"
            context["has_fehbp_address"] = True
        elif "shbp" in msg_lower or "state health benefit" in msg_lower:
            context["account_type"] = "SHBP"
        elif "national" in msg_lower:
            context["Policy.BusinessUnit"] = "National"
            context["account_type"] = "National"
        elif "individual" in msg_lower or "exchange" in msg_lower or "marketplace" in msg_lower:
            context["Policy.MBUCode"] = "IND"
            context["account_type"] = "Individual"

        # Funding type
        if "aso" in msg_lower or "self-funded" in msg_lower or "self funded" in msg_lower:
            context["IsASO"] = True
        elif "fully insured" in msg_lower:
            context["IsASO"] = False
            context["funding_type"] = "Fully Insured"
        else:
            context["IsASO"] = False

        # Expedited
        if "expedited" in msg_lower:
            context["IsVAExpedited"] = True

        # Written vs verbal
        if "written" in msg_lower or "in writing" in msg_lower or "write" in msg_lower:
            context["is_written_request"] = True
            context["IsGandAInWritingAllowed"] = "Yes"
        if "verbal" in msg_lower or "over the phone" in msg_lower or "call" in msg_lower:
            context["IsVerbalGandAAllowed"] = "Yes"

        # Request type
        if "appeal" in msg_lower and "grievance" in msg_lower:
            context["request_type"] = "both"
        elif "appeal" in msg_lower:
            context["request_type"] = "appeal"
        else:
            context["request_type"] = "grievance"

        logger.info(f"Fallback extracted context: {json.dumps(context, indent=2)}")
        return context
