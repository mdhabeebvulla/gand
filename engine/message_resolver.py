"""
Message Resolver
================
Loads Markdown message templates and resolves {{placeholders}} with actual values.
Business analysts edit these .md files directly — no code changes needed.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import markdown

logger = logging.getLogger(__name__)


class MessageResolver:
    """Load and render Markdown message templates."""

    def __init__(self, messages_dir: str = "messages"):
        self.messages_dir = Path(messages_dir)
        self.cache: dict[str, str] = {}
        self._load_all()

    def _load_all(self):
        """Pre-load all .md files into cache."""
        if not self.messages_dir.exists():
            logger.warning(f"Messages directory not found: {self.messages_dir}")
            return

        for md_file in self.messages_dir.glob("*.md"):
            key = md_file.stem  # filename without extension
            content = md_file.read_text(encoding="utf-8")

            # Strip YAML frontmatter (between --- markers)
            parts = content.split("---")
            if len(parts) >= 3:
                body = "---".join(parts[2:]).strip()
            else:
                body = content.strip()

            self.cache[key] = body

        logger.info(f"Loaded {len(self.cache)} message templates from {self.messages_dir}")

    def reload(self):
        """Hot-reload messages from disk."""
        self.cache.clear()
        self._load_all()

    def resolve(
        self,
        message_ref: str,
        context: dict,
        data_source_results: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Load a message template and fill placeholders.

        Args:
            message_ref: Template filename (without .md), e.g. "FEHBP_MEMBER"
            context: Member context for placeholder resolution
            data_source_results: API response data for placeholders like
                                 {{fehbp_address.MailingAddress}}

        Returns:
            dict with 'markdown' (raw) and 'html' (rendered) versions,
            or None if template not found.
        """
        template = self.cache.get(message_ref)
        if template is None:
            logger.warning(f"Message template not found: {message_ref}")
            return None

        ds = data_source_results or {}

        # Resolve all {{placeholder}} patterns
        def replace_placeholder(match):
            placeholder = match.group(1).strip()

            # Try data source reference: "fehbp_address.MailingAddress"
            if "." in placeholder:
                parts = placeholder.split(".", 1)
                source_name = parts[0]

                # Check data sources first
                if source_name in ds:
                    value = ds[source_name].get(parts[1], "")
                    if value:
                        return str(value)

                # Fall back to context with dotted key
                value = context.get(placeholder)
                if value is not None:
                    return str(value)

                # Try just the field name part
                value = context.get(parts[-1])
                if value is not None:
                    return str(value)

            # Direct context lookup
            value = context.get(placeholder)
            if value is not None:
                return str(value)

            logger.warning(f"Unresolved placeholder: {{{{{placeholder}}}}}")
            return f"[{placeholder}]"

        resolved_md = re.sub(r"\{\{(.+?)\}\}", replace_placeholder, template)

        # Convert to HTML
        html = markdown.markdown(resolved_md, extensions=["tables", "nl2br"])

        return {
            "markdown": resolved_md,
            "html": html,
        }

    def list_templates(self) -> list[str]:
        """Return all available template names."""
        return sorted(self.cache.keys())
