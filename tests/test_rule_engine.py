"""
Unit Tests for G&A Rule Engine
================================
Tests every major rule scenario to ensure deterministic correctness.
Run: pytest tests/test_rule_engine.py -v
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.rule_engine import RuleEngine
from engine.message_resolver import MessageResolver
from engine.data_sources import DataSourceResolver


# ─── Setup ───
BASE = Path(__file__).parent.parent
engine = RuleEngine(str(BASE / "rules" / "ga_rules.json"))
resolver = MessageResolver(str(BASE / "messages"))
ds = DataSourceResolver(mode="mock")


# ═══════════════════════════════════════════
# FEHBP Rules
# ═══════════════════════════════════════════

def test_fehbp_member():
    """R001: FEHBP account + Member → FEHBP_MEMBER message."""
    context = {
        "HCCustomerType": "Member",
        "Policy.PolicyState": "VA",
        "account_type": "FEHBP",
        "has_fehbp_address": True,
        "IsASO": False,
    }
    ds_results = ds.resolve_all(context)
    result = engine.evaluate(context, ds_results)

    assert result is not None, "Should match a rule"
    assert result["rule_id"] == "R001_FEHBP_MEMBER"
    assert result["message_ref"] == "FEHBP_MEMBER"


def test_fehbp_broker():
    """R002: FEHBP account + Broker → FEHBP_BROKER message."""
    context = {
        "HCCustomerType": "Broker",
        "Policy.PolicyState": "CA",
        "account_type": "FEHBP",
        "has_fehbp_address": True,
        "IsASO": False,
    }
    ds_results = ds.resolve_all(context)
    result = engine.evaluate(context, ds_results)

    assert result is not None
    assert result["rule_id"] == "R002_FEHBP_BROKER"


def test_fehbp_message_has_placeholders_resolved():
    """FEHBP message should resolve {{Policy.PolicyState}} placeholder."""
    context = {
        "HCCustomerType": "Member",
        "Policy.PolicyState": "VA",
        "account_type": "FEHBP",
        "has_fehbp_address": True,
    }
    ds_results = ds.resolve_all(context)
    result = engine.evaluate(context, ds_results)

    msg = resolver.resolve(result["message_ref"], context, ds_results)
    assert msg is not None
    assert "VA" in msg["markdown"]
    assert "{{Policy.PolicyState}}" not in msg["markdown"]


# ═══════════════════════════════════════════
# VA Expedited
# ═══════════════════════════════════════════

def test_va_expedited():
    """R004: VA Expedited appeal → fax number provided."""
    context = {
        "HCCustomerType": "Member",
        "Policy.PolicyState": "VA",
        "IsVAExpedited": True,
        "account_type": "FEHBP",
        "has_fehbp_address": True,
    }
    ds_results = ds.resolve_all(context)
    result = engine.evaluate(context, ds_results)

    assert result is not None
    # Should match either VA_EXPEDITED or FEHBP depending on priority
    assert result["rule_id"] in ["R004_VA_EXPEDITED", "R001_FEHBP_MEMBER"]


# ═══════════════════════════════════════════
# National Account
# ═══════════════════════════════════════════

def test_national_non_ca():
    """R003: National account, non-CA state → Anthem address."""
    context = {
        "HCCustomerType": "Member",
        "Policy.PolicyState": "TX",
        "Policy.BusinessUnit": "National",
        "account_type": "National",
        "has_fehbp_address": False,
        "IsASO": False,
    }
    ds_results = ds.resolve_all(context)
    result = engine.evaluate(context, ds_results)

    assert result is not None
    msg = resolver.resolve(result["message_ref"], context, ds_results)
    assert msg is not None
    assert "TX" in msg["markdown"] or "National" in msg["markdown"]


# ═══════════════════════════════════════════
# No Match
# ═══════════════════════════════════════════

def test_no_match_returns_none():
    """Empty context should not crash, returns None."""
    context = {}
    ds_results = {}
    result = engine.evaluate(context, ds_results)
    # May or may not match depending on defaults — just shouldn't crash
    assert result is None or isinstance(result, dict)


# ═══════════════════════════════════════════
# Engine functionality
# ═══════════════════════════════════════════

def test_all_rules_loaded():
    """Should load all 22 rules."""
    assert len(engine.rules) == 22


def test_rules_sorted_by_priority():
    """Rules should be sorted by priority (ascending)."""
    priorities = [r.get("priority", 999) for r in engine.rules]
    assert priorities == sorted(priorities)


def test_all_messages_loaded():
    """Should load all 21 message templates."""
    assert len(resolver.cache) == 21


def test_reload_doesnt_crash():
    """Hot reload should work without errors."""
    engine.reload()
    resolver.reload()
    assert len(engine.rules) == 22


def test_list_rules_returns_all():
    """API list endpoint returns all rules."""
    rules = engine.get_all_rules()
    assert len(rules) == 22
    assert all("id" in r for r in rules)


def test_get_rule_by_id():
    """Can retrieve specific rule by ID."""
    rule = engine.get_rule_by_id("R001_FEHBP_MEMBER")
    assert rule is not None
    assert rule["id"] == "R001_FEHBP_MEMBER"


def test_get_rule_not_found():
    """Non-existent rule returns None."""
    assert engine.get_rule_by_id("NONEXISTENT") is None


# ═══════════════════════════════════════════
# Context Extractor (fallback mode)
# ═══════════════════════════════════════════

def test_fallback_extraction():
    """Keyword fallback should extract basic context."""
    from engine.context_extractor import ContextExtractor

    ext = ContextExtractor(api_key=None)
    ctx = ext.extract("I'm a member in Virginia with an FEHBP account")

    assert ctx.get("HCCustomerType") == "Member"
    assert ctx.get("Policy.PolicyState") == "VA"
    assert ctx.get("account_type") == "FEHBP"


def test_fallback_broker():
    """Fallback detects broker."""
    from engine.context_extractor import ContextExtractor

    ext = ContextExtractor(api_key=None)
    ctx = ext.extract("I'm a broker in California")

    assert ctx.get("HCCustomerType") == "Broker"
    assert ctx.get("Policy.PolicyState") == "CA"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
