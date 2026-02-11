"""Plugin loader - discovers and hot-reloads BaseTool subclasses from a directory."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()


class PluginLoader:
    """Discovers and loads BaseTool plugins from a directory.

    Plugin files are Python files in the plugins directory.
    Each file can contain one or more BaseTool subclasses.
    They are automatically discovered and registered in the ToolRegistry.

    Usage:
        loader = PluginLoader("/opt/fochs/plugins", registry)
        loaded = loader.scan_and_load()  # Returns list of loaded tool names
        loader.reload("my_tool")  # Hot-reload a specific plugin
    """

    def __init__(self, plugins_dir: str, registry: ToolRegistry) -> None:
        self._dir = Path(plugins_dir)
        self._registry = registry
        self._loaded_modules: dict[str, str] = {}  # module_name -> file_path

    def scan_and_load(self) -> list[str]:
        """Scan plugins directory and load all valid tool plugins.

        Returns list of loaded tool names.
        """
        if not self._dir.is_dir():
            logger.info("plugins_dir_not_found", path=str(self._dir))
            return []

        loaded: list[str] = []
        for py_file in sorted(self._dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # Skip __init__.py, __pycache__, etc.
            try:
                tools = self._load_file(py_file)
                loaded.extend(tools)
            except Exception as e:
                logger.warning("plugin_load_error", file=str(py_file), error=str(e))

        if loaded:
            logger.info("plugins_loaded", count=len(loaded), tools=loaded)
        return loaded

    def reload(self, plugin_name: str) -> bool:
        """Reload a specific plugin file by its module name.

        Args:
            plugin_name: The module name (filename without .py extension).

        Returns:
            True if reload was successful.
        """
        file_path = self._loaded_modules.get(plugin_name)
        if not file_path:
            # Try to find it
            candidate = self._dir / f"{plugin_name}.py"
            if candidate.is_file():
                file_path = str(candidate)
            else:
                logger.warning("plugin_not_found", name=plugin_name)
                return False

        try:
            self._load_file(Path(file_path))
            logger.info("plugin_reloaded", name=plugin_name)
            return True
        except Exception as e:
            logger.error("plugin_reload_error", name=plugin_name, error=str(e))
            return False

    def _load_file(self, py_file: Path) -> list[str]:
        """Load a single plugin file and register its tools.

        Returns list of tool names from this file.
        """
        module_name = f"fochs_plugin_{py_file.stem}"

        # Read source and exec in a fresh module namespace.
        # This avoids bytecode caching issues with importlib on reload.
        source = py_file.read_text(encoding="utf-8")

        # Create a fresh module
        import types

        module = types.ModuleType(module_name)
        module.__file__ = str(py_file)
        sys.modules[module_name] = module

        # Execute the source in the module namespace
        code = compile(source, str(py_file), "exec")
        exec(code, module.__dict__)  # noqa: S102

        # Find all BaseTool subclasses
        loaded: list[str] = []
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseTool) and obj is not BaseTool:
                try:
                    tool_instance = obj()
                    if tool_instance.name:
                        self._registry.register(tool_instance)
                        loaded.append(tool_instance.name)
                        logger.debug("plugin_tool_registered", tool=tool_instance.name, file=str(py_file))
                except Exception as e:
                    logger.warning(
                        "plugin_tool_init_error",
                        cls=_name,
                        file=str(py_file),
                        error=str(e),
                    )

        # Track the module
        self._loaded_modules[py_file.stem] = str(py_file)
        return loaded

    def list_plugins(self) -> dict[str, str]:
        """Return dict of loaded plugin_name -> file_path."""
        return dict(self._loaded_modules)

    def get_available_files(self) -> list[str]:
        """Return list of .py files in the plugins directory."""
        if not self._dir.is_dir():
            return []
        return [f.name for f in sorted(self._dir.glob("*.py")) if not f.name.startswith("_")]
