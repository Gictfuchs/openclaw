"""Tests for file_read and file_write tools."""

from __future__ import annotations

import pytest

from openclaw.security.shell_guard import ShellGuard
from openclaw.tools.file_tool import FileReadTool, FileWriteTool


class TestFileReadTool:
    def _make_tool(self, mode: str = "restricted") -> FileReadTool:
        guard = ShellGuard(mode=mode, allowed_dirs=["/tmp"])
        return FileReadTool(guard=guard)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path: object) -> None:
        """Read a file that exists."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", dir="/tmp", delete=False) as f:
            f.write("hello fochs")
            fpath = f.name

        tool = self._make_tool(mode="unrestricted")
        result = await tool.execute(path=fpath)
        assert "hello fochs" in result

        Path(fpath).unlink()

    @pytest.mark.asyncio
    async def test_read_nonexistent(self) -> None:
        tool = self._make_tool(mode="unrestricted")
        result = await tool.execute(path="/tmp/nonexistent_xyz_123.txt")
        assert "existiert nicht" in result

    @pytest.mark.asyncio
    async def test_read_directory(self) -> None:
        tool = self._make_tool(mode="unrestricted")
        result = await tool.execute(path="/tmp")
        assert "Inhalt von" in result or "Verzeichnis" in result

    @pytest.mark.asyncio
    async def test_read_blocked_sensitive(self) -> None:
        tool = self._make_tool(mode="unrestricted")
        result = await tool.execute(path="/etc/shadow")
        assert "BLOCKIERT" in result

    @pytest.mark.asyncio
    async def test_read_blocked_outside_allowed(self) -> None:
        tool = self._make_tool(mode="restricted")
        result = await tool.execute(path="/etc/hostname")
        assert "BLOCKIERT" in result

    def test_tool_definition(self) -> None:
        tool = self._make_tool()
        defn = tool.to_definition()
        assert defn["name"] == "file_read"
        assert "path" in defn["input_schema"]["properties"]


class TestFileWriteTool:
    def _make_tool(self, mode: str = "standard") -> FileWriteTool:
        guard = ShellGuard(mode=mode, allowed_dirs=["/tmp"])
        return FileWriteTool(guard=guard)

    @pytest.mark.asyncio
    async def test_write_file(self) -> None:
        from pathlib import Path

        fpath = "/tmp/fochs_test_write.txt"
        tool = self._make_tool(mode="standard")
        result = await tool.execute(path=fpath, content="test content")
        assert "geschrieben" in result

        content = Path(fpath).read_text()
        assert content == "test content"
        Path(fpath).unlink()

    @pytest.mark.asyncio
    async def test_write_append(self) -> None:
        from pathlib import Path

        fpath = "/tmp/fochs_test_append.txt"
        Path(fpath).write_text("first\n")

        tool = self._make_tool(mode="standard")
        result = await tool.execute(path=fpath, content="second\n", append=True)
        assert "angehaengt" in result

        content = Path(fpath).read_text()
        assert content == "first\nsecond\n"
        Path(fpath).unlink()

    @pytest.mark.asyncio
    async def test_write_blocked_restricted(self) -> None:
        tool_guard = ShellGuard(mode="restricted", allowed_dirs=["/tmp"])
        tool = FileWriteTool(guard=tool_guard)
        result = await tool.execute(path="/tmp/test.txt", content="test")
        assert "BLOCKIERT" in result

    @pytest.mark.asyncio
    async def test_write_blocked_sensitive(self) -> None:
        tool = self._make_tool(mode="standard")
        result = await tool.execute(path="/tmp/.env", content="SECRET=bad")
        assert "BLOCKIERT" in result

    @pytest.mark.asyncio
    async def test_write_outside_allowed(self) -> None:
        tool = self._make_tool(mode="standard")
        result = await tool.execute(path="/etc/test.txt", content="nope")
        assert "BLOCKIERT" in result

    @pytest.mark.asyncio
    async def test_make_executable(self) -> None:
        import os
        from pathlib import Path

        fpath = "/tmp/fochs_test_exec.sh"
        tool = self._make_tool(mode="standard")
        result = await tool.execute(path=fpath, content="#!/bin/bash\necho hi", make_executable=True)
        assert "geschrieben" in result

        assert os.access(fpath, os.X_OK)
        Path(fpath).unlink()

    def test_tool_definition(self) -> None:
        tool = self._make_tool()
        defn = tool.to_definition()
        assert defn["name"] == "file_write"
        assert "path" in defn["input_schema"]["properties"]
        assert "content" in defn["input_schema"]["properties"]
