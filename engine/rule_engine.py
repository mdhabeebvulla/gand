"""
Deterministic Rule Engine
=========================
Evaluates JSON rule conditions against a member context dictionary.
This engine is DETERMINISTIC — no AI involved in rule evaluation.

Supports:
  - all/any/not operators (nested)
  - eq, neq, in, not_in, is_empty, is_not_empty, exists_with_value
  - Data source lookups
  - Condition template references
  - Sub-rules
  - First-match evaluation (priority-ordered)
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RuleEngine:
    """Loads JSON rules and evaluates them against member context."""

    def __init__(self, rules_path: str = "rules/ga_rules.json"):
        self.rules_path = Path(rules_path)
        self.config = self._load_rules()
        self.rules = sorted(
            [r for r in self.config.get("rules", []) if r.get("active", True)],
            key=lambda r: r.get("priority", 999),
        )
        self.templates = self.config.get("condition_templates", {})
        self.data_sources = self.config.get("data_sources", {})
        logger.info(f"Loaded {len(self.rules)} active rules from {rules_path}")

    def _load_rules(self) -> dict:
        """Load rules JSON from file."""
        with open(self.rules_path, "r") as f:
            return json.load(f)

    def reload(self):
        """Hot-reload rules from disk (supports dynamic updates)."""
        self.config = self._load_rules()
        self.rules = sorted(
            [r for r in self.config.get("rules", []) if r.get("active", True)],
            key=lambda r: r.get("priority", 999),
        )
        self.templates = self.config.get("condition_templates", {})
        logger.info(f"Reloaded {len(self.rules)} rules")

    def evaluate(
        self, context: dict, data_source_results: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Evaluate all rules against member context.
        Returns the first matching rule (first-match mode).

        Args:
            context: Member context dict, e.g.:
                {
                    "HCCustomerType": "Member",
                    "Policy.PolicyState": "VA",
                    "IsASO": false,
                    ...
                }
            data_source_results: Pre-resolved data source results, e.g.:
                {
                    "fehbp_address": {"MailingAddress": "PO Box 123..."},
                    "group_details": {"FundingTypeCode": "E"},
                    "account_type": {"AccountType": "SHBP"}
                }

        Returns:
            Matching rule dict with id, name, message_ref, placeholders
            or None if no rule matches.
        """
        ds = data_source_results or {}

        for rule in self.rules:
            rule_id = rule.get("id", "unknown")
            conditions = rule.get("conditions", {})

            try:
                if self._evaluate_block(conditions, context, ds):
                    logger.info(f"Rule MATCHED: {rule_id} (priority {rule.get('priority')})")

                    # Check sub-rules if present
                    sub_rules = rule.get("sub_rules", [])
                    if sub_rules:
                        for sub in sub_rules:
                            sub_conds = sub.get("conditions", {})
                            if self._evaluate_block(sub_conds, context, ds):
                                logger.info(f"  Sub-rule matched: {sub.get('id')}")
                                return {
                                    "rule_id": sub.get("id", rule_id),
                                    "parent_rule_id": rule_id,
                                    "name": rule.get("name", ""),
                                    "message_ref": sub.get("message_ref", rule.get("message_ref")),
                                    "placeholders": sub.get("placeholders", rule.get("placeholders", [])),
                                    "priority": rule.get("priority"),
                                    "tags": rule.get("tags", []),
                                }

                    return {
                        "rule_id": rule_id,
                        "name": rule.get("name", ""),
                        "message_ref": rule.get("message_ref", ""),
                        "placeholders": rule.get("placeholders", []),
                        "priority": rule.get("priority"),
                        "tags": rule.get("tags", []),
                    }
            except Exception as e:
                logger.warning(f"Error evaluating rule {rule_id}: {e}")
                continue

        logger.info("No rule matched for given context")
        return None

    def _evaluate_block(self, block: dict, context: dict, ds: dict) -> bool:
        """Evaluate a condition block (all/any/not or single condition)."""

        # Template reference — resolve and evaluate
        if "use_template" in block:
            template_name = block["use_template"]
            template = self.templates.get(template_name)
            if template is None:
                logger.warning(f"Template not found: {template_name}")
                return False
            return self._evaluate_block(template, context, ds)

        # ALL — every condition must be true
        if "all" in block:
            return all(self._evaluate_block(c, context, ds) for c in block["all"])

        # ANY — at least one condition must be true
        if "any" in block:
            return any(self._evaluate_block(c, context, ds) for c in block["any"])

        # NOT — invert the result
        if "not" in block:
            return not self._evaluate_block(block["not"], context, ds)

        # Single condition
        return self._evaluate_condition(block, context, ds)

    def _evaluate_condition(self, cond: dict, context: dict, ds: dict) -> bool:
        """Evaluate a single condition."""
        op = cond.get("op", "eq")

        # Data source check (e.g., "fehbp_address is_not_empty")
        if "source" in cond and "field" not in cond:
            source_name = cond["source"]
            source_data = ds.get(source_name, {})

            if op == "is_not_empty":
                return bool(source_data) and any(
                    v not in (None, "", []) for v in source_data.values()
                )
            elif op == "is_empty":
                return not source_data or all(
                    v in (None, "", []) for v in source_data.values()
                )
            return bool(source_data)

        # Data source field check (e.g., group_details.FundingTypeCode in [E,G,H])
        if "source" in cond and "field" in cond:
            source_name = cond["source"]
            field = cond["field"]
            source_data = ds.get(source_name, {})
            actual = source_data.get(field)
            expected = cond.get("val")
            return self._compare(actual, expected, op)

        # Direct field check from context
        field = cond.get("field", "")
        actual = self._get_field(context, field)
        expected = cond.get("val")

        return self._compare(actual, expected, op)

    def _compare(self, actual: Any, expected: Any, op: str) -> bool:
        """Compare actual value against expected using operator."""
        if op in ("eq", "equals"):
            return self._normalize(actual) == self._normalize(expected)

        elif op in ("neq", "not_equals"):
            return self._normalize(actual) != self._normalize(expected)

        elif op == "in":
            if isinstance(expected, list):
                return self._normalize(actual) in [self._normalize(e) for e in expected]
            return self._normalize(actual) == self._normalize(expected)

        elif op == "not_in":
            if isinstance(expected, list):
                return self._normalize(actual) not in [self._normalize(e) for e in expected]
            return self._normalize(actual) != self._normalize(expected)

        elif op == "is_empty":
            return actual in (None, "", [], False, 0)

        elif op == "is_not_empty":
            return actual not in (None, "", [], False, 0)

        elif op == "exists_with_value":
            return actual is not None and actual != "" and actual != []

        elif op == "is_empty_or_false":
            return actual in (None, "", [], False, 0, "false", "False")

        else:
            logger.warning(f"Unknown operator: {op}")
            return False

    def _get_field(self, context: dict, field: str) -> Any:
        """
        Get field value from context.
        Supports dotted paths: 'Policy.PolicyState' looks up:
          1. context['Policy.PolicyState']  (flat key)
          2. context['Policy']['PolicyState']  (nested)
          3. context['PolicyState']  (short name fallback)
        """
        # Try flat key first
        if field in context:
            return context[field]

        # Try nested path
        parts = field.split(".")
        current = context
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                # Fallback: try the last segment
                return context.get(parts[-1])
        return current

    def _normalize(self, val: Any) -> Any:
        """Normalize values for comparison (case-insensitive strings, bool handling)."""
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            low = val.lower().strip()
            if low == "true":
                return True
            if low == "false":
                return False
            return low
        return val

    def get_all_rules(self) -> list:
        """Return all rules with metadata (for /api/rules endpoint)."""
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "priority": r.get("priority"),
                "active": r.get("active", True),
                "tags": r.get("tags", []),
                "message_ref": r.get("message_ref"),
            }
            for r in self.rules
        ]

    def get_rule_by_id(self, rule_id: str) -> Optional[dict]:
        """Return a specific rule by ID."""
        for r in self.rules:
            if r.get("id") == rule_id:
                return r
        return None
