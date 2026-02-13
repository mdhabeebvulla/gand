"""
Bitbucket REST API Client
==========================
Reads and writes files (rules JSON + message Markdown) to a Bitbucket repo.

Uses Bitbucket REST API 2.0:
  - GET    /src/{branch}/{path}         → read file
  - GET    /src/{branch}/{path}/        → list directory
  - POST   /src                         → commit file changes
  - GET    /commits                     → commit history
  - GET    /diff/{spec}                 → file diff

Authentication: App Password (username + app_password)
  → Generate at: https://bitbucket.org/account/settings/app-passwords/
  → Required permissions: Repositories (Read, Write)

Docs: https://developer.atlassian.com/cloud/bitbucket/rest/intro/
"""

import base64
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bitbucket.org/2.0/repositories"


class BitbucketClient:
    """Client for Bitbucket REST API 2.0."""

    def __init__(
        self,
        workspace: Optional[str] = None,
        repo_slug: Optional[str] = None,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        branch: str = "main",
    ):
        self.workspace = workspace or os.getenv("BB_WORKSPACE", "")
        self.repo_slug = repo_slug or os.getenv("BB_REPO_SLUG", "")
        self.username = username or os.getenv("BB_USERNAME", "")
        self.app_password = app_password or os.getenv("BB_APP_PASSWORD", "")
        self.branch = branch or os.getenv("BB_BRANCH", "main")

        self.base = f"{BASE_URL}/{self.workspace}/{self.repo_slug}"
        self._auth = (self.username, self.app_password) if self.username else None

        self.configured = bool(self.workspace and self.repo_slug and self.username and self.app_password)
        if self.configured:
            logger.info(f"Bitbucket client: {self.workspace}/{self.repo_slug} (branch: {self.branch})")
        else:
            logger.warning("Bitbucket not configured — admin will use local file mode")

    # ─────────────────────────────────────────
    # READ operations
    # ─────────────────────────────────────────

    async def get_file(self, file_path: str) -> Optional[str]:
        """
        Read a file from the repo.

        Args:
            file_path: e.g. "rules/ga_rules.json" or "messages/FEHBP_MEMBER.md"

        Returns:
            File content as string, or None if not found.
        """
        if not self.configured:
            return self._local_read(file_path)

        url = f"{self.base}/src/{self.branch}/{file_path}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=self._auth, timeout=15)
                if resp.status_code == 200:
                    return resp.text
                logger.warning(f"BB get_file {file_path}: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"BB get_file error: {e}")
            return None

    async def list_files(self, dir_path: str) -> list[dict]:
        """
        List files in a directory.

        Returns:
            List of {path, size, type} dicts.
        """
        if not self.configured:
            return self._local_list(dir_path)

        url = f"{self.base}/src/{self.branch}/{dir_path}/"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=self._auth, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    return [
                        {
                            "path": v.get("path", ""),
                            "size": v.get("size", 0),
                            "type": v.get("type", ""),
                        }
                        for v in data.get("values", [])
                    ]
                return []
        except Exception as e:
            logger.error(f"BB list_files error: {e}")
            return []

    # ─────────────────────────────────────────
    # WRITE operations
    # ─────────────────────────────────────────

    async def commit_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        author: str = "G&A Admin <ga-admin@company.com>",
    ) -> dict:
        """
        Commit a file change to the repo.

        Args:
            file_path: e.g. "rules/ga_rules.json"
            content: New file content
            commit_message: Commit message
            author: Author string

        Returns:
            {success: bool, commit_hash: str, message: str}
        """
        if not self.configured:
            return self._local_write(file_path, content, commit_message)

        url = f"{self.base}/src"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    auth=self._auth,
                    data={
                        file_path: content,
                        "message": commit_message,
                        "author": author,
                        "branch": self.branch,
                    },
                    timeout=30,
                )
                if resp.status_code in (200, 201):
                    logger.info(f"BB committed {file_path}: {commit_message}")
                    return {
                        "success": True,
                        "commit_hash": resp.headers.get("Location", "").split("/")[-1],
                        "message": f"Committed to {self.branch}: {commit_message}",
                    }
                else:
                    body = resp.text[:500]
                    logger.error(f"BB commit failed: HTTP {resp.status_code} — {body}")
                    return {
                        "success": False,
                        "commit_hash": "",
                        "message": f"Bitbucket error {resp.status_code}: {body}",
                    }
        except Exception as e:
            logger.error(f"BB commit error: {e}")
            return {"success": False, "commit_hash": "", "message": str(e)}

    async def commit_multiple(
        self,
        files: dict[str, str],
        commit_message: str,
        author: str = "G&A Admin <ga-admin@company.com>",
    ) -> dict:
        """
        Commit multiple files in a single commit.

        Args:
            files: {file_path: content, ...}
            commit_message: Commit message
        """
        if not self.configured:
            for path, content in files.items():
                self._local_write(path, content, commit_message)
            return {"success": True, "commit_hash": "local", "message": "Saved locally"}

        url = f"{self.base}/src"
        try:
            data = {**files, "message": commit_message, "author": author, "branch": self.branch}
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, auth=self._auth, data=data, timeout=30)
                if resp.status_code in (200, 201):
                    return {
                        "success": True,
                        "commit_hash": resp.headers.get("Location", "").split("/")[-1],
                        "message": f"Committed {len(files)} files to {self.branch}",
                    }
                return {
                    "success": False,
                    "commit_hash": "",
                    "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }
        except Exception as e:
            return {"success": False, "commit_hash": "", "message": str(e)}

    # ─────────────────────────────────────────
    # HISTORY
    # ─────────────────────────────────────────

    async def get_commits(self, file_path: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Get recent commits, optionally filtered by file path."""
        if not self.configured:
            return [{"hash": "local", "message": "Local mode — no history", "date": "", "author": ""}]

        url = f"{self.base}/commits/{self.branch}"
        params = {"pagelen": limit}
        if file_path:
            params["path"] = file_path

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=self._auth, params=params, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    return [
                        {
                            "hash": c.get("hash", "")[:8],
                            "message": c.get("message", "").strip(),
                            "date": c.get("date", ""),
                            "author": c.get("author", {}).get("raw", ""),
                        }
                        for c in data.get("values", [])
                    ]
                return []
        except Exception as e:
            logger.error(f"BB get_commits error: {e}")
            return []

    # ─────────────────────────────────────────
    # LOCAL FALLBACK (when Bitbucket not configured)
    # ─────────────────────────────────────────

    def _get_base_dir(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent

    def _local_read(self, file_path: str) -> Optional[str]:
        """Read from local filesystem."""
        full = self._get_base_dir() / file_path
        if full.exists():
            return full.read_text(encoding="utf-8")
        return None

    def _local_write(self, file_path: str, content: str, msg: str) -> dict:
        """Write to local filesystem."""
        full = self._get_base_dir() / file_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        logger.info(f"Local save: {file_path} ({msg})")
        return {"success": True, "commit_hash": "local", "message": f"Saved locally: {msg}"}

    def _local_list(self, dir_path: str) -> list[dict]:
        """List local files."""
        from pathlib import Path
        d = self._get_base_dir() / dir_path
        if not d.exists():
            return []
        return [
            {"path": str(f.relative_to(self._get_base_dir())), "size": f.stat().st_size, "type": "commit_file"}
            for f in sorted(d.iterdir())
            if f.is_file()
        ]
