"""
Data Source Resolver
====================
Resolves external data source lookups (FEHBP address, GroupDetails, AccountType).

For POC: Returns mock data based on context.
For Production: Replace mock methods with real HTTP calls to actual APIs.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DataSourceResolver:
    """
    Resolve data from external APIs / DataPages.

    In POC mode, returns mock data.
    In production, each method makes actual HTTP calls.
    """

    def __init__(self, mode: str = "mock"):
        self.mode = mode
        logger.info(f"DataSourceResolver initialized in {mode} mode")

    def resolve_all(self, context: dict) -> dict:
        """
        Resolve all data sources based on member context.

        Returns:
            {
                "fehbp_address": {"MailingAddress": "...", ...} or {},
                "group_details": {"FundingTypeCode": "E", ...} or {},
                "account_type": {"AccountType": "SHBP", ...} or {}
            }
        """
        results = {
            "fehbp_address": self._resolve_fehbp(context),
            "group_details": self._resolve_group_details(context),
            "account_type": self._resolve_account_type(context),
        }

        logger.info(f"Resolved data sources: { {k: bool(v) for k, v in results.items()} }")
        return results

    def _resolve_fehbp(self, context: dict) -> dict:
        """
        D_FEHBPCaseandAddressData lookup.

        Production: HTTP call to FEHBP API with Policy.GroupNumber.
        POC: Return mock address if account_type is FEHBP.
        """
        account_type = context.get("account_type", "")
        has_fehbp = context.get("has_fehbp_address", False)

        if account_type == "FEHBP" or has_fehbp:
            state = context.get("Policy.PolicyState", "VA")
            return {
                "MailingAddress": (
                    f"FEHBP Grievance & Appeals\n"
                    f"P.O. Box 21542\n"
                    f"Eagan, MN 55121"
                ),
                "AddressHeader": "FEHBP G&A Department",
                "AddressLine1": "P.O. Box 21542",
                "AddressLine2": "Eagan, MN 55121",
                "Department": "Grievance and Appeals",
            }
        return {}

    def _resolve_group_details(self, context: dict) -> dict:
        """
        D_GroupDetails via ApexWGSGroupDetails API.

        Production: POST to /v2/group/details with GroupID, SourceSystemInd, etc.
        POC: Return mock funding type.
        """
        funding = context.get("funding_type", "")
        is_aso = context.get("IsASO", False)

        if is_aso:
            return {"FundingTypeCode": "A"}  # ASO
        elif funding == "Fully Insured":
            return {"FundingTypeCode": "E"}  # Fully Insured
        else:
            # Default: return empty to let other conditions determine
            return {"FundingTypeCode": ""}

    def _resolve_account_type(self, context: dict) -> dict:
        """
        D_AccountType lookup.

        Production: Lookup by GroupNumber.
        POC: Return from context.
        """
        account = context.get("account_type", "")

        if account == "SHBP":
            return {"AccountType": "SHBP"}
        elif account == "National":
            return {"AccountType": "National"}
        elif account == "FEHBP":
            return {"AccountType": "FEHBP"}
        elif account in ("Individual", "Exchange"):
            return {"AccountType": "Individual"}
        else:
            return {"AccountType": ""}
