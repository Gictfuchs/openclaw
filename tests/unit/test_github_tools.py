"""Tests for GitHub tools."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.integrations.github import GitHubClient, IssueInfo, RepoInfo
from openclaw.tools.github_tools import GitHubCreateIssueTool, GitHubIssuesTool, GitHubRepoTool


@pytest.fixture
def mock_gh_client():
    client = MagicMock(spec=GitHubClient)
    return client


class TestGitHubRepoTool:
    async def test_returns_repo_info(self, mock_gh_client: MagicMock) -> None:
        mock_gh_client.get_repo_info.return_value = RepoInfo(
            full_name="owner/repo",
            description="A test repo",
            stars=42,
            open_issues=5,
            language="Python",
            updated_at=datetime(2025, 1, 15),
            default_branch="main",
        )

        tool = GitHubRepoTool(client=mock_gh_client)
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=mock_gh_client.get_repo_info.return_value,
            )
            result = await tool.execute(repo="owner/repo")

        assert "owner/repo" in result
        assert "42" in result
        assert "Python" in result
        assert "A test repo" in result

    async def test_handles_error(self, mock_gh_client: MagicMock) -> None:
        tool = GitHubRepoTool(client=mock_gh_client)
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("Not found"),
            )
            result = await tool.execute(repo="bad/repo")

        assert "Error" in result

    def test_tool_definition(self, mock_gh_client: MagicMock) -> None:
        tool = GitHubRepoTool(client=mock_gh_client)
        defn = tool.to_definition()
        assert defn["name"] == "github_repo"
        assert "repo" in defn["input_schema"]["properties"]


class TestGitHubIssuesTool:
    async def test_returns_issues(self, mock_gh_client: MagicMock) -> None:
        mock_gh_client.list_issues.return_value = [
            IssueInfo(
                number=1, title="Bug fix", state="open", author="user1",
                labels=["bug"], is_pr=False, url="https://github.com/owner/repo/issues/1",
            ),
            IssueInfo(
                number=2, title="Add feature", state="open", author="user2",
                labels=[], is_pr=True, url="https://github.com/owner/repo/pull/2",
            ),
        ]

        tool = GitHubIssuesTool(client=mock_gh_client)
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=mock_gh_client.list_issues.return_value,
            )
            result = await tool.execute(repo="owner/repo")

        assert "#1" in result
        assert "Bug fix" in result
        assert "bug" in result
        assert "#2" in result
        assert "PR" in result

    async def test_no_issues(self, mock_gh_client: MagicMock) -> None:
        tool = GitHubIssuesTool(client=mock_gh_client)
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=[])
            result = await tool.execute(repo="owner/repo")

        assert "No open issues" in result


class TestGitHubCreateIssueTool:
    async def test_creates_issue(self, mock_gh_client: MagicMock) -> None:
        mock_gh_client.create_issue.return_value = IssueInfo(
            number=42, title="New issue", state="open", author="bot",
            url="https://github.com/owner/repo/issues/42",
        )

        tool = GitHubCreateIssueTool(client=mock_gh_client)
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=mock_gh_client.create_issue.return_value,
            )
            result = await tool.execute(repo="owner/repo", title="New issue")

        assert "#42" in result
        assert "New issue" in result
        assert "https://github.com" in result
