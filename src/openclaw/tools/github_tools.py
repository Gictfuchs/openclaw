"""GitHub tools for the agent."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from openclaw.integrations.github import GitHubClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class GitHubRepoTool(BaseTool):
    """Get information about a GitHub repository."""

    name = "github_repo"
    description = (
        "Get information about a GitHub repository including stars, issues, language, and recent activity. "
        "Input: owner/repo format (e.g. 'anthropics/claude-code')."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/repo' format.",
            },
        },
        "required": ["repo"],
    }

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        repo_name = kwargs["repo"]

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, self._client.get_repo_info, repo_name)
        except Exception as e:
            return f"Error fetching repo '{repo_name}': {e}"

        updated = info.updated_at.strftime("%Y-%m-%d") if info.updated_at else "unknown"
        return (
            f"Repository: {info.full_name}\n"
            f"Description: {info.description}\n"
            f"Language: {info.language}\n"
            f"Stars: {info.stars}\n"
            f"Open Issues: {info.open_issues}\n"
            f"Default Branch: {info.default_branch}\n"
            f"Last Updated: {updated}"
        )


class GitHubIssuesTool(BaseTool):
    """List issues for a GitHub repository."""

    name = "github_issues"
    description = (
        "List issues (and PRs) for a GitHub repository. "
        "Returns title, state, author, and labels."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/repo' format.",
            },
            "state": {
                "type": "string",
                "description": "Filter by state: 'open', 'closed', or 'all'.",
                "enum": ["open", "closed", "all"],
            },
            "limit": {
                "type": "integer",
                "description": "Max number of issues to return (default 10).",
            },
        },
        "required": ["repo"],
    }

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        repo_name = kwargs["repo"]
        state = kwargs.get("state", "open")
        limit = min(kwargs.get("limit", 10), 25)

        try:
            loop = asyncio.get_event_loop()
            issues = await loop.run_in_executor(
                None, lambda: self._client.list_issues(repo_name, state=state, limit=limit),
            )
        except Exception as e:
            return f"Error fetching issues for '{repo_name}': {e}"

        if not issues:
            return f"No {state} issues found for {repo_name}."

        parts = [f"Issues for {repo_name} ({state}):\n"]
        for issue in issues:
            kind = "PR" if issue.is_pr else "Issue"
            labels_str = f" [{', '.join(issue.labels)}]" if issue.labels else ""
            parts.append(f"#{issue.number} ({kind}) {issue.title}{labels_str} - by {issue.author}")

        return "\n".join(parts)


class GitHubCreateIssueTool(BaseTool):
    """Create a new GitHub issue."""

    name = "github_create_issue"
    description = "Create a new issue in a GitHub repository."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/repo' format.",
            },
            "title": {
                "type": "string",
                "description": "Issue title.",
            },
            "body": {
                "type": "string",
                "description": "Issue body/description (Markdown supported).",
            },
        },
        "required": ["repo", "title"],
    }

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        repo_name = kwargs["repo"]
        title = kwargs["title"]
        body = kwargs.get("body", "")

        try:
            loop = asyncio.get_event_loop()
            issue = await loop.run_in_executor(
                None, lambda: self._client.create_issue(repo_name, title=title, body=body),
            )
        except Exception as e:
            return f"Error creating issue in '{repo_name}': {e}"

        return f"Issue created: #{issue.number} - {issue.title}\n{issue.url}"
