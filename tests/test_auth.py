import json
import tempfile
import unittest
from pathlib import Path

from security.auth import AuthConfigError, get_token, load_auth_config


class AuthTests(unittest.TestCase):
    def test_token_is_loaded_from_environment_reference(self):
        config = {"github": {"token_env": "GITHUB_TOKEN"}}

        token = get_token(
            "github",
            config,
            {"GITHUB_TOKEN": "token-value"}
        )

        self.assertEqual(token, "token-value")

    def test_missing_token_fails_closed(self):
        with self.assertRaises(AuthConfigError):
            get_token(
                "github",
                {"github": {"token_env": "GITHUB_TOKEN"}},
                {}
            )

    def test_auth_config_is_loaded_from_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(
                json.dumps({"github": {"token_env": "GITHUB_TOKEN"}}),
                encoding="utf-8"
            )

            config = load_auth_config(path)

        self.assertEqual(config["github"]["token_env"], "GITHUB_TOKEN")


if __name__ == "__main__":
    unittest.main()
