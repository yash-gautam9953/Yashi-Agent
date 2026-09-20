# Yashi-Agent 🤖🛡️

**Yashi-Agent** is a secure, autonomous, and self-extending AI coding and system assistant built in Python. Powered by Azure OpenAI (Responses API) and configured with strict security boundaries, it pairs the convenience of an autonomous multi-tool agent with strict human-in-the-loop safeguards and dynamic tool synthesis.

---

## ✨ Features

- **🔄 Autonomous Multi-Tool Loop**: Runs multi-turn tool loops (up to 12 bounded rounds) to inspect, edit, verify, and complete complex developer workflows.
- **🛡️ Secure by Design**:
  - **Workspace Confinement**: Enforces path isolation to prevent path traversal outside the project directory.
  - **Sensitive File Protection**: Automatically blocks reading or modifying sensitive files (`.env`, `credentials.json`, `.key`, `.pem`, SSH keys, etc.).
  - **Secret Redaction**: Regex-based redaction dynamically masks API keys, bearer tokens, and passwords from terminal output and model context.
  - **Restricted Command Runner**: Blocks shell chaining operators (`&`, `|`, `;`, `>`, etc.), enforces execution timeouts (30s), limits output size (12KB), and requires approval for risky commands.
- **👤 Human-in-the-Loop Approvals**: Read-only operations run automatically; destructive or external actions (overwrites, deletes, external filesystem reads, git commits/pushes, risky shell commands) strictly require interactive `[y/N]` approval.
- **⚡ Dynamic Self-Extending Tools (Hot-Reloading)**:
  - When the agent encounters a task needing a tool that doesn't exist, it can write a new Python tool and its JSON schema.
  - Automatically verifies syntax using Python's `ast.parse` and runs tests in an isolated subprocess before prompting for user approval.
  - **Hot-reloads** the tool into active memory without stopping or restarting the session, enabling the agent to use it immediately on the next step.
  - Persists custom tools in `custom_tools/` and `config/custom_tools.json` so they remain available on future launches.
- **📁 Comprehensive Toolset**:
  - **Filesystem**: `read_file`, `create_file`, `edit_file`, `delete_file`, `rename_file`, `list_directory`, `file_metadata`, `search_files`, `search_media`.
  - **Cross-Drive Navigation**: `list_drives`, `list_location`, `read_external_file` (gated by user approval).
  - **Dedicated Git Suite**: Safe read operations (`git_status`, `git_diff`, `git_log`, `git_branch`) and approved state changes (`git_create_branch`, `git_commit`, `git_push`, `git_pull`, `git_checkout`).
  - **Workflows**: `create_workflow` and `run_workflow` to orchestrate reusable pipelines of existing tools.

---

## 📂 Project Structure

```
Yashi-Agent/
├── main.py                     # Agent entry point & REPL execution loop
├── tools.json                  # OpenAI function calling tool schemas
├── ROADMAP.md                  # Development phases and milestones
├── README.md                   # Project documentation
│
├── config/                     # Configuration files
│   ├── assistant.json          # Media search extensions and root limits
│   ├── auth.json               # Provider configs pointing to environment variables
│   ├── auth.local.example.json # Example authentication template
│   └── custom_tools.json       # Persistent registry of dynamic custom tools
│
├── custom_tools/               # Directory where agent-created tools reside
│   └── __init__.py
│
├── security/                   # Security boundary & filtering modules
│   ├── auth.py                 # Safe token loading from environment
│   ├── path_policy.py          # Workspace containment & sensitive path blocking
│   └── secret_redaction.py     # Regex-based credential and bearer redaction
│
├── tools/                      # Core tool implementations
│   ├── computer_files.py       # Drive enumeration & external path inspection
│   ├── custom_tool_manager.py  # Validation, subprocess testing & hot-reloading
│   ├── filesystem.py           # Workspace file manipulation & media search
│   ├── git.py                  # Dedicated, safe Git operations
│   ├── tool_builder.py         # Static tool proposal generator
│   └── workflows.py            # Composable, multi-step tool pipelines
│
├── ui/                         # User Interface
│   └── console.py              # Colored terminal output, banners & approval prompts
│
└── tests/                      # Offline unit tests (36 tests, 100% passing)
    ├── test_auth.py
    ├── test_computer_files.py
    ├── test_custom_tools.py
    ├── test_filesystem.py
    ├── test_git.py
    ├── test_tool_builder.py
    └── test_workflows.py
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.10+**
- **Git** installed and available in PATH
- **Azure OpenAI Access** (configured with Managed Identity / `DefaultAzureCredential`)

### Installation

1. Clone or open the repository:
   ```bash
   cd Yashi-Agent
   ```

2. Install required packages:
   ```bash
   pip install openai azure-identity
   ```

3. Ensure Azure CLI is authenticated or configure appropriate Azure credentials:
   ```bash
   az login
   ```

---

## 💻 Usage

Start the interactive agent terminal:

```bash
python main.py
```

Once running, you can ask the agent to perform coding tasks, search files, inspect Git repositories, or generate new tools:

```text
========================================================================
  PERSONAL AGENT  |  secure multi-tool session
  Type 'help' for commands, 'exit' to stop.
========================================================================
You > list the files in this project
```

### Interactive Approval Prompts

When the agent attempts an action that modifies files or reads external locations, it will pause and prompt for your approval:

```text
APPROVAL REQUIRED
  Overwrite existing file 'app.py'?
  Allow? [y/N] y
  approved
```

---

## 🧪 Running Tests

All unit tests are self-contained and run completely offline without making external LLM or network requests:

```bash
python -m unittest discover -s tests
```

Output:
```
....................................
----------------------------------------------------------------------
Ran 36 tests in ~9s

OK
```

---

## 🛣️ Roadmap

- [x] **Phase 1: Filesystem, Terminal, Git, & Dynamic Tools** (Implemented & Validated)
- [ ] **Phase 2: Browser, Web Research & Downloads** (Playwright integration, URL validation)
- [ ] **Phase 3: Desktop, Clipboard & Screen Control** (Guarded screenshot & window interaction)
- [ ] **Phase 4: Docker & DevOps** (Constrained container & cloud inspection)
- [ ] **Phase 5: MCP, Memory & Observability** (Model Context Protocol & SQLite persistent memory)
- [ ] **Phase 6: Hardening** (Expanded boundary security & fail-closed resilience)

For more details, see [ROADMAP.md](ROADMAP.md).
