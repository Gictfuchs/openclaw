"""Tests for plugin loader."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openclaw.plugins.loader import PluginLoader
from openclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from pathlib import Path


class TestPluginLoader:
    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry)
        loaded = loader.scan_and_load()
        assert loaded == []

    def test_scan_nonexistent_dir(self) -> None:
        registry = ToolRegistry()
        loader = PluginLoader("/nonexistent_dir_xyz", registry)
        loaded = loader.scan_and_load()
        assert loaded == []

    def test_load_valid_plugin(self, tmp_path: Path) -> None:
        # Create a plugin file
        plugin_code = """
from openclaw.tools.base import BaseTool
from typing import Any

class HelloTool(BaseTool):
    name = "hello_plugin"
    description = "Says hello"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> str:
        return "Hello from plugin!"
"""
        (tmp_path / "hello.py").write_text(plugin_code)

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry, allow_unsigned=True)
        loaded = loader.scan_and_load()

        assert "hello_plugin" in loaded
        assert registry.get("hello_plugin") is not None

    def test_skip_underscore_files(self, tmp_path: Path) -> None:
        (tmp_path / "__init__.py").write_text("# nothing")
        (tmp_path / "_private.py").write_text("# nothing")

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry)
        loaded = loader.scan_and_load()
        assert loaded == []

    def test_bad_plugin_does_not_crash(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("raise RuntimeError('broken')")

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry)
        loaded = loader.scan_and_load()
        assert loaded == []

    def test_reload_plugin(self, tmp_path: Path) -> None:
        plugin_code_v1 = """
from openclaw.tools.base import BaseTool
from typing import Any

class VersionTool(BaseTool):
    name = "version_plugin"
    description = "v1"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    async def execute(self, **kwargs: Any) -> str:
        return "v1"
"""
        (tmp_path / "version.py").write_text(plugin_code_v1)

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry, allow_unsigned=True)
        loader.scan_and_load()

        tool = registry.get("version_plugin")
        assert tool is not None
        assert tool.description == "v1"

        # Update plugin
        plugin_code_v2 = plugin_code_v1.replace("v1", "v2")
        (tmp_path / "version.py").write_text(plugin_code_v2)

        result = loader.reload("version")
        assert result is True

        tool = registry.get("version_plugin")
        assert tool is not None
        assert tool.description == "v2"

    def test_reload_nonexistent(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry)
        assert loader.reload("nonexistent") is False

    def test_list_plugins(self, tmp_path: Path) -> None:
        (tmp_path / "my_tool.py").write_text(
            "from openclaw.tools.base import BaseTool\n"
            "from typing import Any\n"
            "class MyTool(BaseTool):\n"
            '    name="my_t"\n'
            '    description="test"\n'
            '    parameters: dict[str, Any] = {"type":"object","properties":{}}\n'
            '    async def execute(self, **kwargs: Any) -> str: return "ok"\n'
        )

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry, allow_unsigned=True)
        loader.scan_and_load()

        plugins = loader.list_plugins()
        assert "my_tool" in plugins

    def test_get_available_files(self, tmp_path: Path) -> None:
        (tmp_path / "tool_a.py").write_text("# a")
        (tmp_path / "tool_b.py").write_text("# b")
        (tmp_path / "__init__.py").write_text("# skip")

        registry = ToolRegistry()
        loader = PluginLoader(str(tmp_path), registry)
        files = loader.get_available_files()
        assert "tool_a.py" in files
        assert "tool_b.py" in files
        assert "__init__.py" not in files
