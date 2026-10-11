import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from memory.session_store import (
    SessionData,
    SessionStore,
    sanitize_for_storage,
    sanitize_text,
)


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.sessions_dir = self.workspace / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.store = SessionStore(storage_dir=self.sessions_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_session(self):
        """Test persistent saving of conversation, tool calls, and metadata to JSON."""
        self.store.add_message("user", "Please calculate the checksum of data.")
        self.store.record_tool_call(
            tool_name="calculate_sha256",
            arguments={"text": "hello"},
            output="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            status="success",
        )
        self.store.record_approved_tool(
            name="calculate_sha256",
            version="1.0.0",
            permissions=["pure_computation"],
            risk_level="low",
        )
        self.store.record_rejected_attempt(
            tool_name="failed_tool",
            attempt=1,
            reason="AssertionError: test failure",
            error_type="AssertionError",
        )
        self.store.add_message("assistant", "The checksum is calculated.")
        self.store.update_response_id("resp_test_123")

        session_file = self.sessions_dir / f"{self.store.active_session_id}.json"
        self.assertTrue(session_file.exists())

        raw = json.loads(session_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["session_id"], self.store.active_session_id)
        self.assertEqual(raw["response_id"], "resp_test_123")
        self.assertEqual(len(raw["messages"]), 2)
        self.assertEqual(raw["messages"][0]["role"], "user")
        self.assertEqual(raw["messages"][1]["role"], "assistant")
        self.assertEqual(len(raw["tool_calls"]), 1)
        self.assertEqual(raw["tool_calls"][0]["tool_name"], "calculate_sha256")
        self.assertEqual(len(raw["tool_metadata"]), 1)
        self.assertEqual(raw["tool_metadata"][0]["name"], "calculate_sha256")
        self.assertEqual(len(raw["debug_rejected_attempts"]), 1)
        self.assertEqual(raw["debug_rejected_attempts"][0]["error_type"], "AssertionError")

    def test_load_session(self):
        """Test loading a previous session when explicitly requested."""
        # Create and populate session 1
        sess_1 = self.store.new_session("session_1")
        self.store.add_message("user", "Hello from session 1")
        self.store.add_message("assistant", "Response in session 1")
        self.store.save()

        # Create session 2
        sess_2 = self.store.new_session("session_2")
        self.store.add_message("user", "Hello from session 2")
        self.store.save()
        self.assertEqual(self.store.active_session_id, "session_2")

        # Explicitly load session 1
        loaded = self.store.load_session("session_1")
        self.assertIsNotNone(loaded)
        self.assertEqual(self.store.active_session_id, "session_1")
        self.assertEqual(len(self.store.get_messages()), 2)
        self.assertEqual(self.store.get_messages()[0]["content"], "Hello from session 1")

        # Attempt to load non-existent session
        missing = self.store.load_session("non_existent_session")
        self.assertIsNone(missing)

    def test_new_session(self):
        """Test creating a fresh session generates a new ID and clears active turns."""
        first_id = self.store.active_session_id
        self.store.add_message("user", "First session message")

        # Start new session
        new_sess = self.store.new_session()
        self.assertNotEqual(new_sess.session_id, first_id)
        self.assertEqual(self.store.active_session_id, new_sess.session_id)
        self.assertEqual(len(self.store.get_messages()), 0)
        self.assertEqual(len(self.store.get_tool_calls()), 0)

        # Both session files exist on disk
        sessions = self.store.list_sessions()
        session_ids = [s["session_id"] for s in sessions]
        self.assertIn(first_id, session_ids)
        self.assertIn(new_sess.session_id, session_ids)

    def test_clearing_history(self):
        """Test clearing current session history and all saved sessions."""
        self.store.add_message("user", "Temporary data to clear")
        active_id = self.store.active_session_id
        session_file = self.sessions_dir / f"{active_id}.json"
        self.assertTrue(session_file.exists())

        # Clear active session
        self.store.clear()
        self.assertFalse(session_file.exists())
        self.assertNotEqual(self.store.active_session_id, active_id)
        self.assertEqual(len(self.store.get_messages()), 0)

        # Create multiple sessions and clear all
        self.store.new_session("batch_1")
        self.store.new_session("batch_2")
        self.assertGreaterEqual(len(list(self.sessions_dir.glob("*.json"))), 2)

        cleared_count = self.store.clear_all()
        self.assertGreaterEqual(cleared_count, 2)
        self.assertEqual(len(self.store.get_messages()), 0)

    def test_corrupted_storage_recovery(self):
        """Test system safely recovers when loading corrupted storage without crashing."""
        corrupted_file = self.sessions_dir / "corrupted_sess.json"
        # Truncated broken JSON
        corrupted_file.write_text('{"session_id": "corrupted_sess", "messages": [{"role": "us', encoding="utf-8")

        # load_session should recover rather than crashing
        recovered = self.store.load_session("corrupted_sess")
        self.assertIsNotNone(recovered)
        self.assertEqual(self.store.active_session_id, "corrupted_sess")
        # Verify backup was created
        self.assertTrue((self.sessions_dir / "corrupted_sess.corrupted").exists())
        # Verify valid JSON file replaced it
        valid_json = json.loads(corrupted_file.read_text(encoding="utf-8"))
        self.assertEqual(valid_json["session_id"], "corrupted_sess")

        # list_sessions should also handle corrupt files gracefully
        bad_file = self.sessions_dir / "bad_syntax.json"
        bad_file.write_text("NOT_JSON_AT_ALL!!!", encoding="utf-8")
        summaries = self.store.list_sessions()
        self.assertTrue(any(s["session_id"] == "bad_syntax" and s.get("corrupted") for s in summaries))

    def test_secret_filtering(self):
        """Test API keys, passwords, Bearer tokens, and raw .env contents are never stored."""
        os.environ["AZURE_OPENAI_API_KEY"] = "secret-azure-api-key-998877665544332211"
        os.environ["CUSTOM_SECRET_TOKEN"] = "token-secret-alpha-bravo-charlie-99"

        # 1. Message with raw .env content
        raw_env = (
            "AZURE_OPENAI_API_KEY=secret-azure-api-key-998877665544332211\n"
            "AZURE_OPENAI_ENDPOINT=https://example.com\n"
            "SECRET_PASSWORD=MyPassword123!\n"
            "sk-proj-12345678901234567890abcdef"
        )
        self.store.add_message("user", raw_env)

        # 2. Tool call with sensitive argument dictionary
        self.store.record_tool_call(
            tool_name="http_request",
            arguments={
                "url": "https://api.example.com",
                "api_key": "secret-azure-api-key-998877665544332211",
                "headers": {"Authorization": "Bearer abcdef1234567890abcdef1234"},
                "password": "ClearTextPassword!",
            },
            output="Authentication token: Bearer abcdef1234567890abcdef1234",
        )

        session_file = self.sessions_dir / f"{self.store.active_session_id}.json"
        saved_text = session_file.read_text(encoding="utf-8")

        # Strict assertions: zero raw secrets stored
        self.assertNotIn("secret-azure-api-key-998877665544332211", saved_text)
        self.assertNotIn("token-secret-alpha-bravo-charlie-99", saved_text)
        self.assertNotIn("MyPassword123!", saved_text)
        self.assertNotIn("ClearTextPassword!", saved_text)
        self.assertNotIn("sk-proj-12345678901234567890", saved_text)

        # Verify redactions present
        self.assertIn("[REDACTED_SECRET]", saved_text)

    def test_orchestrator_integration(self):
        """Test AgentOrchestrator records user turns and tool calls in SessionStore."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_round_1"
        mock_response.output = []
        mock_response.output_text = "Task completed successfully."
        mock_llm.create_response.return_value = mock_response

        registry = MagicMock()
        registry.schemas = []

        from agent.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator(
            llm_client=mock_llm,
            registry=registry,
            session_store=self.store,
        )

        resp_id = orchestrator.run_task("What is the current time?")
        self.assertEqual(resp_id, "resp_round_1")

        # Verify messages in store
        messages = self.store.get_messages()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "What is the current time?")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "Task completed successfully.")
        self.assertEqual(self.store.response_id, "resp_round_1")


if __name__ == "__main__":
    unittest.main()
