"""GitHub API client wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from github import Auth, Github, GithubException

if TYPE_CHECKING:
    from datetime import datetime

logger = structlog.get_logger()


@dataclass
class RepoInfo:
    """Summary of a GitHub repository."""

    full_name: str
    description: str
    stars: int
    open_issues: int
    language: str
    updated_at: datetime | None = None
    default_branch: str = "main"


@dataclass
class IssueInfo:
    """Summary of a GitHub issue or PR."""

    number: int
    title: str
    state: str
    author: str
    created_at: datetime | None = None
    labels: list[str] = field(default_factory=list)
    is_pr: bool = False
    url: str = ""


class GitHubClient:
    """Wrapper around PyGithub for async-friendly usage.

    Note: PyGithub is synchronous. We wrap calls but don't block the event loop
    for long since GitHub API calls are fast. For heavy usage, consider
    running in executor.
    """

    def __init__(self, token: str) -> None:
        self._gh = Github(auth=Auth.Token(token))

    def get_repo_info(self, repo_name: str) -> RepoInfo:
        """Get repository summary. repo_name format: 'owner/repo'."""
        try:
            repo = self._gh.get_repo(repo_name)
            return RepoInfo(
                full_name=repo.full_name,
                description=repo.description or "",
                stars=repo.stargazers_count,
                open_issues=repo.open_issues_count,
                language=repo.language or "unknown",
                updated_at=repo.updated_at,
                default_branch=repo.default_branch,
            )
        except GithubException as e:
            logger.error("github_repo_error", repo=repo_name, error=str(e))
            raise

    def list_issues(
        self,
        repo_name: str,
        state: str = "open",
        limit: int = 10,
    ) -> list[IssueInfo]:
        """List issues for a repository."""
        try:
            repo = self._gh.get_repo(repo_name)
            issues = repo.get_issues(state=state, sort="updated", direction="desc")
            result = []
            for issue in issues[:limit]:
                result.append(
                    IssueInfo(
                        number=issue.number,
                        title=issue.title,
                        state=issue.state,
                        author=issue.user.login if issue.user else "unknown",
                        created_at=issue.created_at,
                        labels=[label.name for label in issue.labels],
                        is_pr=issue.pull_request is not None,
                        url=issue.html_url,
                    )
                )
            return result
        except GithubException as e:
            logger.error("github_issues_error", repo=repo_name, error=str(e))
            raise

    def create_issue(
        self,
        repo_name: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> IssueInfo:
        """Create a new issue."""
        try:
            repo = self._gh.get_repo(repo_name)
            issue = repo.create_issue(title=title, body=body, labels=labels or [])
            return IssueInfo(
                number=issue.number,
                title=issue.title,
                state=issue.state,
                author=issue.user.login if issue.user else "unknown",
                created_at=issue.created_at,
                url=issue.html_url,
            )
        except GithubException as e:
            logger.error("github_create_issue_error", repo=repo_name, error=str(e))
            raise

    def get_recent_activity(self, repo_name: str, limit: int = 10) -> list[str]:
        """Get recent events (commits, issues, PRs) for a repo."""
        try:
            repo = self._gh.get_repo(repo_name)
            events = repo.get_events()
            result = []
            for event in events[:limit]:
                actor = event.actor.login if event.actor else "unknown"
                created = event.created_at.strftime("%Y-%m-%d %H:%M") if event.created_at else ""
                result.append(f"[{created}] {event.type} by {actor}")
            return result
        except GithubException as e:
            logger.error("github_activity_error", repo=repo_name, error=str(e))
            raise

    def close(self) -> None:
        self._gh.close()
