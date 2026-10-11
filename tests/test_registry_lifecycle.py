import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.registry import ToolManifest, ToolRegistry
from tools.custom_tool_manager import (
    create_and_register_tool,
    import_custom_tool,
)


class RegistryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        (self.workspace / "custom_tools").mkdir(parents=True, exist_ok=True)
        (self.workspace / "config").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_registration_with_metadata(self):
        """Test full metadata manifest registration, retrieval, and serialization."""
        registry = ToolRegistry()
        dummy_schema = {
            "type": "function",
            "name": "pdf_scanner",
            "description": "Finds PDF files and reports their sizes.",
            "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}},
        }
        manifest = ToolManifest(
            name="pdf_scanner",
            description="Finds PDF files and reports their sizes.",
            schema=dummy_schema,
            function_name="pdf_scanner",
            file="pdf_scanner.py",
            version="1.0.0",
            author="agent",
            dependencies=["pypdf"],
            permissions=["read_directory"],
            risk_level="low",
            enabled=True,
            status="approved",
            checksum="abc123sha",
        )
        registry.register_tool(
            name="pdf_scanner",
            schema=dummy_schema,
            function=lambda directory: ["doc.pdf"],
            manifest=manifest,
        )

        self.assertIn("pdf_scanner", registry.manifests)
        registered_manifest = registry.manifests["pdf_scanner"]
        self.assertEqual(registered_manifest.version, "1.0.0")
        self.assertEqual(registered_manifest.author, "agent")
        self.assertEqual(registered_manifest.dependencies, ["pypdf"])
        self.assertEqual(registered_manifest.permissions, ["read_directory"])
        self.assertEqual(registered_manifest.risk_level, "low")
        self.assertTrue(registered_manifest.enabled)
        self.assertEqual(registered_manifest.status, "approved")
        self.assertEqual(registered_manifest.checksum, "abc123sha")

        # Verify serialization round-trip
        m_dict = registered_manifest.to_dict()
        reconstructed = ToolManifest.from_dict(m_dict)
        self.assertEqual(reconstructed.name, "pdf_scanner")
        self.assertEqual(reconstructed.checksum, "abc123sha")
        self.assertEqual(reconstructed.dependencies, ["pypdf"])

        # Check schemas includes enabled tool
        schema_names = [s["name"] for s in registry.schemas]
        self.assertIn("pdf_scanner", schema_names)

    def test_duplicate_detection(self):
        """Test deterministic duplicate detection for exact names, synonyms, and capabilities."""
        registry = ToolRegistry()
        write_schema = {
            "type": "function",
            "name": "write_text_file",
            "description": "Write text content to a destination file on disk.",
            "parameters": {"type": "object", "properties": {}},
        }
        manifest = ToolManifest(
            name="write_text_file",
            description="Write text content to a destination file on disk.",
            schema=write_schema,
            function_name="write_text_file",
            file="write_text_file.py",
            version="1.0.0",
        )
        registry.register_tool("write_text_file", write_schema, lambda: None, manifest)

        # 1. Exact name match
        dup_exact = registry.find_duplicate("write_text_file", "any description")
        self.assertIsNotNone(dup_exact)
        self.assertEqual(dup_exact["match_type"], "exact_name")
        self.assertEqual(dup_exact["tool"], "write_text_file")

        # 2. Semantic synonym overlap (save_text_file -> write_text_file)
        dup_synonym = registry.find_duplicate("save_text_file", "save content to a file")
        self.assertIsNotNone(dup_synonym)
        self.assertEqual(dup_synonym["tool"], "write_text_file")

        # 3. High capability overlap
        dup_capability = registry.find_duplicate("disk_writer", "Write text content to destination file on disk")
        self.assertIsNotNone(dup_capability)
        self.assertEqual(dup_capability["tool"], "write_text_file")

        # 4. Distinct tool -> no duplicate
        dup_none = registry.find_duplicate("calculator", "Perform basic arithmetic calculations")
        self.assertIsNone(dup_none)

    def test_create_and_register_duplicate_rejection(self):
        """Test that create_and_register_tool rejects generating a duplicate tool when one exists."""
        # Pre-seed config with existing tool
        config_file = self.workspace / "config" / "custom_tools.json"
        config_data = {
            "write_text_file": {
                "name": "write_text_file",
                "version": "1.0.0",
                "description": "Writes text into files",
                "file": "write_text_file.py",
                "function_name": "write_text_file",
                "enabled": True,
                "status": "approved",
                "schema": {
                    "type": "function",
                    "name": "write_text_file",
                    "description": "Writes text into files",
                },
            }
        }
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        # Attempt to create duplicate tool
        result_str = create_and_register_tool(
            self.workspace,
            lambda _: True,
            lambda *_: None,
            {"create_and_register_tool"},
            "save_text_file",
            "Writes text into files on disk",
            {"type": "object", "properties": {}},
            "def save_text_file(): pass",
            "assert True",
        )

        data = json.loads(result_str)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "duplicate_found")
        self.assertEqual(data["existing_tool"], "write_text_file")
        self.assertIn("suggestion", data)
        self.assertIn("write_text_file", data["suggestion"])

    def test_enable_and_disable(self):
        """Test enabling and disabling tools and verifying schema visibility."""
        registry = ToolRegistry()
        schema = {
            "type": "function",
            "name": "helper_tool",
            "description": "Does some helper work",
        }
        manifest = ToolManifest(
            name="helper_tool",
            description="Does some helper work",
            schema=schema,
            function_name="helper_tool",
            file="helper_tool.py",
        )
        registry.register_tool("helper_tool", schema, lambda: "ok", manifest)

        # Initially enabled
        self.assertIn("helper_tool", [s["name"] for s in registry.schemas])

        # Disable tool
        success = registry.disable_tool("helper_tool", self.workspace)
        self.assertTrue(success)
        self.assertFalse(registry.manifests["helper_tool"].enabled)
        self.assertEqual(registry.manifests["helper_tool"].status, "disabled")
        # Excluded from active LLM schemas
        self.assertNotIn("helper_tool", [s["name"] for s in registry.schemas])
        # But still present in all_schemas for UI commands
        self.assertIn("helper_tool", [s["name"] for s in registry.all_schemas])

        # Core tool create_and_register_tool cannot be disabled
        cannot_disable = registry.disable_tool("create_and_register_tool", self.workspace)
        self.assertFalse(cannot_disable)

        # Re-enable tool
        enable_success = registry.enable_tool("helper_tool", self.workspace)
        self.assertTrue(enable_success)
        self.assertTrue(registry.manifests["helper_tool"].enabled)
        self.assertEqual(registry.manifests["helper_tool"].status, "approved")
        self.assertIn("helper_tool", [s["name"] for s in registry.schemas])

    def test_delete_tool_with_confirmation_and_cleanup(self):
        """Test deleting a tool removes its file, config, and manifests."""
        registry = ToolRegistry()
        tool_file = self.workspace / "custom_tools" / "temp_remover.py"
        tool_file.write_text("def temp_remover(): pass\n", encoding="utf-8")

        schema = {
            "type": "function",
            "name": "temp_remover",
            "description": "Temporary tool to be deleted",
        }
        manifest = ToolManifest(
            name="temp_remover",
            description="Temporary tool to be deleted",
            schema=schema,
            function_name="temp_remover",
            file="temp_remover.py",
        )
        registry.register_tool("temp_remover", schema, lambda: None, manifest)
        registry.save_manifests_to_disk(self.workspace)

        self.assertTrue(tool_file.exists())
        self.assertIn("temp_remover", registry.manifests)

        # Attempt to delete core system tool -> rejected
        self.assertFalse(registry.delete_tool("create_and_register_tool", self.workspace))

        # Successfully delete tool
        deleted = registry.delete_tool("temp_remover", self.workspace)
        self.assertTrue(deleted)
        self.assertFalse(tool_file.exists())
        self.assertNotIn("temp_remover", registry.manifests)
        self.assertNotIn("temp_remover", registry.functions)
        self.assertNotIn("temp_remover", [s["name"] for s in registry.schemas])

        # Verify disk config was also updated
        config_path = self.workspace / "config" / "custom_tools.json"
        saved_data = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertNotIn("temp_remover", saved_data)

    def test_version_metadata_and_history(self):
        """Test version bumping, checksum generation, and revision history tracking."""
        registry = ToolRegistry()
        tool_file = self.workspace / "custom_tools" / "text_stats.py"
        code_v1 = "def text_stats(text: str):\n    return {'chars': len(text)}\n"
        code_v2 = "def text_stats(text: str):\n    return {'chars': len(text), 'words': len(text.split())}\n"
        tool_file.write_text(code_v1, encoding="utf-8")

        csum_v1 = hashlib.sha256(code_v1.strip().encode("utf-8")).hexdigest()[:16]
        schema = {
            "type": "function",
            "name": "text_stats",
            "description": "Computes text statistics",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
        manifest = ToolManifest(
            name="text_stats",
            description="Computes text statistics",
            schema=schema,
            function_name="text_stats",
            file="text_stats.py",
            version="1.0.0",
            checksum=csum_v1,
        )
        registry.register_tool("text_stats", schema, lambda text: {"chars": len(text)}, manifest)

        self.assertEqual(manifest.version, "1.0.0")
        self.assertEqual(len(manifest.history), 0)

        # Update tool to version 1.1.0 using update_tool
        updated = registry.update_tool(
            name="text_stats",
            workspace=self.workspace,
            code=code_v2,
            description="Computes detailed text statistics (chars and words)",
            new_version="1.1.0",
        )
        self.assertTrue(updated)

        updated_manifest = registry.manifests["text_stats"]
        self.assertEqual(updated_manifest.version, "1.1.0")
        self.assertEqual(len(updated_manifest.history), 1)

        hist = updated_manifest.history[0]
        self.assertEqual(hist["version"], "1.0.0")
        self.assertEqual(hist["checksum"], csum_v1)
        self.assertEqual(hist["description"], "Computes text statistics")

        csum_v2 = hashlib.sha256(code_v2.strip().encode("utf-8")).hexdigest()[:16]
        self.assertEqual(updated_manifest.checksum, csum_v2)

        # Verify history retrieval method
        history_list = registry.get_tool_history("text_stats")
        self.assertEqual(len(history_list), 1)
        self.assertEqual(history_list[0]["version"], "1.0.0")

    def test_loading_registry_on_startup(self):
        """Test loading registry manifests from disk on application startup."""
        tool_a_file = self.workspace / "custom_tools" / "tool_a.py"
        tool_a_file.write_text("def tool_a():\n    return 'a'\n", encoding="utf-8")
        tool_b_file = self.workspace / "custom_tools" / "tool_b.py"
        tool_b_file.write_text("def tool_b():\n    return 'b'\n", encoding="utf-8")

        config_file = self.workspace / "config" / "custom_tools.json"
        config_data = {
            "tool_a": {
                "name": "tool_a",
                "version": "1.2.0",
                "description": "Tool A active on startup",
                "file": "tool_a.py",
                "function_name": "tool_a",
                "permissions": ["test_perm"],
                "dependencies": [],
                "risk_level": "low",
                "enabled": True,
                "status": "approved",
                "schema": {
                    "type": "function",
                    "name": "tool_a",
                    "description": "Tool A active on startup",
                },
            },
            "tool_b": {
                "name": "tool_b",
                "version": "1.0.0",
                "description": "Tool B disabled",
                "file": "tool_b.py",
                "function_name": "tool_b",
                "permissions": [],
                "dependencies": [],
                "risk_level": "low",
                "enabled": False,
                "status": "disabled",
                "schema": {
                    "type": "function",
                    "name": "tool_b",
                    "description": "Tool B disabled",
                },
            },
        }
        config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        registry = ToolRegistry()
        loaded = registry.load_custom_tools(self.workspace)

        # Only enabled tools are returned as active loaded tools
        self.assertIn("tool_a", loaded)
        self.assertNotIn("tool_b", loaded)

        # Tool A is registered and visible in schemas
        self.assertTrue(registry.has_tool("tool_a"))
        self.assertEqual(registry.manifests["tool_a"].version, "1.2.0")
        self.assertTrue(registry.manifests["tool_a"].enabled)
        self.assertIn("tool_a", [s["name"] for s in registry.schemas])

        # Tool B manifest is loaded but excluded from active schemas
        self.assertIn("tool_b", registry.manifests)
        self.assertFalse(registry.manifests["tool_b"].enabled)
        self.assertNotIn("tool_b", [s["name"] for s in registry.schemas])


if __name__ == "__main__":
    unittest.main()
