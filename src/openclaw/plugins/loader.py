"""Plugin loader - discovers and hot-reloads BaseTool subclasses from a directory.

Security: All plugin files are verified via SHA-256 hash allowlist before
exec(). Unsigned plugins are rejected unless ``allow_unsigned=True``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()

# Maximum plugin file size (512 KB) — prevents loading absurdly large files
_MAX_PLUGIN_SIZE = 512 * 1024


class PluginLoader:
    """Discovers and loads BaseTool plugins from a directory.

    Plugin files are Python files in the plugins directory.
    Each file can contain one or more BaseTool subclasses.
    They are automatically discovered and registered in the ToolRegistry.

    Security:
        A ``plugins.sha256`` manifest in the plugins directory lists
        approved file hashes.  When ``allow_unsigned=False`` (default),
        plugins not in the manifest are rejected.

    Usage:
        loader = PluginLoader("/opt/fochs/plugins", registry)
        loaded = loader.scan_and_load()  # Returns list of loaded tool names
        loader.reload("my_tool")  # Hot-reload a specific plugin
    """

    def __init__(
        self,
        plugins_dir: str,
        registry: ToolRegistry,
        *,
        allow_unsigned: bool = False,
    ) -> None:
        self._dir = Path(plugins_dir)
        self._registry = registry
        self._allow_unsigned = allow_unsigned
        self._loaded_modules: dict[str, str] = {}  # module_name -> file_path
        self._manifest: dict[str, str] = {}  # filename -> sha256 hex
        self._load_manifest()

    def _load_manifest(self) -> None:
        """Load the ``plugins.sha256`` hash manifest if present."""
        manifest_path = self._dir / "plugins.sha256"
        if not manifest_path.is_file():
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._manifest = {k: v.lower() for k, v in data.items()}
                logger.info("plugin_manifest_loaded", entries=len(self._manifest))
        except Exception as e:
            logger.warning("plugin_manifest_load_error", error=str(e))

    @staticmethod
    def _file_sha256(path: Path) -> str:
        """Compute the SHA-256 hex digest of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _verify_integrity(self, py_file: Path) -> bool:
        """Verify a plugin file against the manifest.

        Returns True if the file is trusted (hash matches manifest
        or ``allow_unsigned`` is enabled).
        """
        actual_hash = self._file_sha256(py_file)

        if self._manifest:
            expected = self._manifest.get(py_file.name)
            if expected is None:
                if self._allow_unsigned:
                    logger.warning(
                        "plugin_unsigned",
                        file=py_file.name,
                        sha256=actual_hash,
                        msg="Not in manifest but allow_unsigned=True",
                    )
                    return True
                logger.error(
                    "plugin_rejected_not_in_manifest",
                    file=py_file.name,
                    sha256=actual_hash,
                )
                return False
            if actual_hash != expected:
                logger.error(
                    "plugin_hash_mismatch",
                    file=py_file.name,
                    expected=expected,
                    actual=actual_hash,
                )
                return False
            return True

        # No manifest present — fall back to allow_unsigned flag
        if not self._allow_unsigned:
            logger.warning(
                "plugin_no_manifest",
                file=py_file.name,
                sha256=actual_hash,
                msg="No plugins.sha256 manifest found. Set allow_unsigned=True to load.",
            )
            return False
        return True

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

        Security:
        - File size is checked against ``_MAX_PLUGIN_SIZE``
        - File hash is verified against ``plugins.sha256`` manifest
        - Only files passing integrity checks are exec'd
        """
        module_name = f"fochs_plugin_{py_file.stem}"

        # --- Size check ---
        file_size = py_file.stat().st_size
        if file_size > _MAX_PLUGIN_SIZE:
            msg = f"Plugin too large: {file_size} bytes (max {_MAX_PLUGIN_SIZE})"
            logger.error("plugin_too_large", file=py_file.name, size=file_size)
            raise ValueError(msg)

        # --- Integrity verification ---
        if not self._verify_integrity(py_file):
            msg = f"Plugin integrity check failed for {py_file.name}"
            raise PermissionError(msg)

        # Read source and exec in a fresh module namespace.
        # This avoids bytecode caching issues with importlib on reload.
        source = py_file.read_text(encoding="utf-8")

        # Create a fresh module
        import types

        module = types.ModuleType(module_name)
        module.__file__ = str(py_file)

        # Execute the source in the module namespace
        code = compile(source, str(py_file), "exec")
        try:
            exec(code, module.__dict__)  # noqa: S102
        except Exception:
            # Don't leave a broken module in sys.modules
            sys.modules.pop(module_name, None)
            raise
        # Only register the module after successful exec
        sys.modules[module_name] = module

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

    def generate_manifest(self) -> dict[str, str]:
        """Generate a SHA-256 manifest for all plugin files.

        Returns dict of filename -> sha256 hex digest.
        Useful for creating/updating the ``plugins.sha256`` file.
        """
        manifest: dict[str, str] = {}
        if not self._dir.is_dir():
            return manifest
        for py_file in sorted(self._dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            manifest[py_file.name] = self._file_sha256(py_file)
        return manifest

    def save_manifest(self) -> Path:
        """Generate and save the manifest to ``plugins.sha256``."""
        manifest = self.generate_manifest()
        manifest_path = self._dir / "plugins.sha256"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("plugin_manifest_saved", path=str(manifest_path), entries=len(manifest))
        return manifest_path
