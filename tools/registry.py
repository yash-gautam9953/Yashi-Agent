import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from tools.custom_tool_manager import (
    import_custom_tool,
    validate_tool_name,
)


class ToolManifest:
    """Metadata container for a registered tool."""

    def __init__(
        self,
        name: str,
        description: str,
        schema: Optional[dict] = None,
        function_name: str = "",
        file: str = "",
        version: str = "1.0.0",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        author: str = "agent",
        dependencies: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        risk_level: str = "low",
        enabled: bool = True,
        status: str = "approved",
        checksum: str = "",
        history: Optional[List[dict]] = None,
    ):
        now = datetime.now(timezone.utc).isoformat()
        self.name = name
        self.description = description
        self.schema = schema or {}
        self.function_name = function_name or name
        self.file = file or f"{name}.py"
        self.version = version
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.author = author
        self.dependencies = dependencies or []
        self.permissions = permissions or []
        self.risk_level = risk_level
        self.enabled = enabled
        self.status = status
        self.checksum = checksum
        self.history = history or []

    def update_version(
        self,
        new_version: Optional[str] = None,
        new_checksum: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> str:
        """Bump version and record previous version in history."""
        now = datetime.now(timezone.utc).isoformat()
        self.history.append({
            "version": self.version,
            "updated_at": self.updated_at,
            "checksum": self.checksum,
            "description": self.description,
        })
        self.updated_at = now
        if new_checksum:
            self.checksum = new_checksum
        if new_description:
            self.description = new_description
        if new_version:
            self.version = new_version
        else:
            parts = self.version.split(".")
            if len(parts) == 3 and parts[2].isdigit():
                self.version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
            elif len(parts) == 3 and parts[1].isdigit():
                self.version = f"{parts[0]}.{int(parts[1]) + 1}.0"
            else:
                self.version = f"{self.version}.1"
        return self.version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "file": self.file,
            "function_name": self.function_name,
            "author": self.author,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "risk_level": self.risk_level,
            "enabled": self.enabled,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "checksum": self.checksum,
            "history": self.history,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolManifest":
        schema = data.get("schema", {})
        name = data.get("name") or schema.get("name", "unknown")
        description = data.get("description") or schema.get("description", "")
        function_name = data.get("function_name") or name
        file = data.get("file") or f"{name}.py"

        return cls(
            name=name,
            description=description,
            schema=schema,
            function_name=function_name,
            file=file,
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            author=data.get("author", "custom"),
            dependencies=data.get("dependencies", []),
            permissions=data.get("permissions", []),
            risk_level=data.get("risk_level", "low"),
            enabled=data.get("enabled", True),
            status=data.get("status", "approved"),
            checksum=data.get("checksum", ""),
            history=data.get("history", []),
        )


class ToolRegistry:
    """Manages available tool schemas, metadata manifests, and lifecycle operations."""

    def __init__(self):
        self._schemas: List[dict] = []
        self._functions: Dict[str, Callable[..., Any]] = {}
        self._manifests: Dict[str, ToolManifest] = {}

    @property
    def schemas(self) -> List[dict]:
        """Returns schemas for only currently enabled tools."""
        return [
            s for s in self._schemas
            if s.get("name") not in self._manifests or self._manifests[s.get("name")].enabled
        ]

    @property
    def all_schemas(self) -> List[dict]:
        """Returns schemas for all tools including disabled ones."""
        return self._schemas

    @property
    def functions(self) -> Dict[str, Callable[..., Any]]:
        return self._functions

    @property
    def manifests(self) -> Dict[str, ToolManifest]:
        return self._manifests

    def load_base_tools(self, tools_json_path: Path) -> None:
        """Load static base tool schemas from a JSON file."""
        if tools_json_path.exists():
            data = json.loads(tools_json_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._schemas = [tool for tool in data if isinstance(tool, dict)]
                for tool in self._schemas:
                    tname = tool.get("name")
                    if tname and tname not in self._manifests:
                        self._manifests[tname] = ToolManifest(
                            name=tname,
                            version="1.0.0",
                            description=tool.get("description", "Built-in tool"),
                            schema=tool,
                            file="tools.json",
                            function_name=tname,
                            author="system",
                            enabled=True,
                            status="approved",
                        )

    def bind_function(self, name: str, function: Callable[..., Any]) -> None:
        """Bind a callable to an existing registered schema."""
        self._functions[name] = function

    def register_tool(
        self,
        name: str,
        schema: dict,
        function: Callable[..., Any],
        manifest: Optional[ToolManifest] = None,
    ) -> None:
        """Register or update a tool in the registry."""
        self._functions[name] = function
        self._schemas[:] = [tool for tool in self._schemas if tool.get("name") != name]
        self._schemas.append(schema)

        if manifest:
            self._manifests[name] = manifest
        elif name not in self._manifests:
            self._manifests[name] = ToolManifest(
                name=name,
                description=schema.get("description", ""),
                schema=schema,
                function_name=name,
                file=f"{name}.py",
                author="system",
                enabled=True,
                status="approved",
            )

    def register_custom_tool(
        self,
        name: str,
        schema: dict,
        function: Callable[..., Any],
        manifest: Optional[ToolManifest] = None,
    ) -> None:
        """Register a custom generated tool, ensuring no conflict with core tools."""
        validate_tool_name(name, {"create_and_register_tool"})
        self.register_tool(name, schema, function, manifest=manifest)

    def load_custom_tools(self, workspace: Path) -> List[str]:
        """Load persisted custom tools and manifests from workspace config."""
        config_file = workspace / "config" / "custom_tools.json"
        if not config_file.exists():
            return []

        try:
            raw_data = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(raw_data, dict):
            return []

        loaded_tools = []
        for name, item in raw_data.items():
            if not isinstance(item, dict):
                continue

            manifest = ToolManifest.from_dict(item)
            self._manifests[name] = manifest

            schema = manifest.schema
            if not schema:
                continue

            try:
                func = import_custom_tool(workspace, name)
                self._functions[name] = func

                # Keep schemas updated in memory
                for idx, existing in enumerate(self._schemas):
                    if existing.get("name") == name:
                        self._schemas[idx] = schema
                        break
                else:
                    self._schemas.append(schema)

                if manifest.enabled:
                    loaded_tools.append(name)
            except Exception as error:
                print(f"Warning: Failed to load custom tool '{name}': {error}")

        return loaded_tools

    def save_manifests_to_disk(self, workspace: Path) -> None:
        """Persist all custom tool manifests to config/custom_tools.json."""
        config_file = workspace / "config" / "custom_tools.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            name: m.to_dict()
            for name, m in self._manifests.items()
            if name != "create_and_register_tool"
        }
        config_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def get_manifest(self, name: str) -> Optional[ToolManifest]:
        return self._manifests.get(name)

    def get_function(self, name: str) -> Optional[Callable[..., Any]]:
        manifest = self._manifests.get(name)
        if manifest and not manifest.enabled:
            return None
        return self._functions.get(name)

    def has_tool(self, name: str, check_enabled: bool = True) -> bool:
        if name not in self._functions:
            return False
        if check_enabled and name in self._manifests:
            return self._manifests[name].enabled
        return True

    def find_duplicate(self, name: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Deterministically check if an enabled tool with matching name or capability already exists."""
        # 1. Exact name match
        if name in self._manifests:
            m = self._manifests[name]
            if m.enabled:
                return {
                    "match_type": "exact_name",
                    "tool": name,
                    "reason": f"Tool '{name}' already exists and is active.",
                    "manifest": m.to_dict(),
                }

        # 2. Tokenized & normalized name / description matching
        synonyms = {
            "save": "write",
            "create": "write",
            "make": "write",
            "dump": "write",
            "fetch": "read",
            "load": "read",
            "get": "read",
            "inspect": "read",
            "remove": "delete",
            "erase": "delete",
            "drop": "delete",
            "find": "search",
            "scan": "search",
            "lookup": "search",
            "add": "math",
            "sum": "math",
            "calc": "math",
            "calculate": "math",
        }
        stopwords = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
            "is", "user", "specified", "with", "into", "from", "that", "this"
        }

        def get_tokens(text: str) -> Set[str]:
            words = re.findall(r"[a-z0-9]+", text.lower())
            tokens = set()
            for w in words:
                if w not in stopwords:
                    tokens.add(synonyms.get(w, w))
            return tokens

        query_name_tokens = get_tokens(name)
        query_desc_tokens = get_tokens(description)

        for tool_name, manifest in self._manifests.items():
            if not manifest.enabled or tool_name == "create_and_register_tool":
                continue

            tool_name_tokens = get_tokens(tool_name)
            tool_desc_tokens = get_tokens(manifest.description)

            # Name-based synonym overlap (e.g. save_text_file vs write_text_file)
            if query_name_tokens and tool_name_tokens:
                overlap = len(query_name_tokens & tool_name_tokens) / max(len(query_name_tokens), len(tool_name_tokens))
                if overlap >= 0.66:
                    return {
                        "match_type": "name_similarity",
                        "tool": tool_name,
                        "reason": f"Existing tool '{tool_name}' performs the same operation (name token overlap: {int(overlap * 100)}%).",
                        "manifest": manifest.to_dict(),
                    }

            # Capability description overlap (Jaccard similarity)
            if query_desc_tokens and tool_desc_tokens:
                intersection = query_desc_tokens & tool_desc_tokens
                union = query_desc_tokens | tool_desc_tokens
                jaccard = len(intersection) / len(union) if union else 0.0
                if jaccard >= 0.40 or (len(intersection) >= 3 and len(intersection) / len(query_desc_tokens) >= 0.6):
                    return {
                        "match_type": "capability_overlap",
                        "tool": tool_name,
                        "reason": f"Existing tool '{tool_name}' description closely matches requested capability ({len(intersection)} matching terms).",
                        "manifest": manifest.to_dict(),
                    }

        return None

    def enable_tool(self, name: str, workspace: Optional[Path] = None) -> bool:
        """Enable a disabled tool."""
        manifest = self._manifests.get(name)
        if not manifest:
            return False
        manifest.enabled = True
        manifest.status = "approved"
        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        if workspace:
            self.save_manifests_to_disk(workspace)
        return True

    def disable_tool(self, name: str, workspace: Optional[Path] = None) -> bool:
        """Disable an active tool (excludes it from LLM schema list)."""
        if name == "create_and_register_tool":
            return False
        manifest = self._manifests.get(name)
        if not manifest:
            return False
        manifest.enabled = False
        manifest.status = "disabled"
        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        if workspace:
            self.save_manifests_to_disk(workspace)
        return True

    def delete_tool(self, name: str, workspace: Path) -> bool:
        """Permanently delete a tool file and manifest."""
        if name == "create_and_register_tool":
            return False
        if name not in self._manifests:
            return False

        # Remove file from custom_tools
        tool_file = workspace / "custom_tools" / f"{name}.py"
        if tool_file.exists():
            tool_file.unlink()

        # Remove from internal structures
        self._manifests.pop(name, None)
        self._functions.pop(name, None)
        self._schemas[:] = [tool for tool in self._schemas if tool.get("name") != name]

        # Update disk config
        self.save_manifests_to_disk(workspace)
        return True

    def get_tool_history(self, name: str) -> List[dict]:
        """Return revision history of the given tool."""
        manifest = self._manifests.get(name)
        if not manifest:
            return []
        return manifest.history

    def update_tool(
        self,
        name: str,
        workspace: Path,
        code: str,
        description: Optional[str] = None,
        parameters: Optional[dict] = None,
        new_version: Optional[str] = None,
    ) -> bool:
        """Update an existing tool's code, bump version, and record history."""
        manifest = self._manifests.get(name)
        if not manifest or name == "create_and_register_tool":
            return False

        tool_file = workspace / "custom_tools" / f"{name}.py"
        tool_file.write_text(code, encoding="utf-8")

        csum = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()[:16]
        manifest.update_version(
            new_version=new_version,
            new_checksum=csum,
            new_description=description or manifest.description,
        )

        if description:
            manifest.description = description
            if manifest.schema:
                manifest.schema["description"] = description
        if parameters and manifest.schema:
            manifest.schema["parameters"] = parameters

        func = import_custom_tool(workspace, name)
        self.register_tool(name, manifest.schema, func, manifest)
        self.save_manifests_to_disk(workspace)
        return True

