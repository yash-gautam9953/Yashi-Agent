# Personal Agent Roadmap

## Current architecture

- `main.py`: Azure Responses API client, dynamic tool registry, and bounded multi-tool loop.
- `tools/`: filesystem, Git, workflow, and custom tool management.
- `custom_tools/`: dynamic agent-generated and user-approved tools.
- `security/`: workspace path policy and secret redaction.
- `config/`: provider settings (`auth.json`), media settings (`assistant.json`), and dynamic tool registry (`custom_tools.json`).
- `tools.json`: LLM tool schemas.
- `tests/`: standard-library unit tests that do not call the LLM.

## Phase 1: Filesystem, terminal, Git, and dynamic tools

Status: implemented and validated.

- Workspace-safe file read, search, create, edit, rename, and directory creation.
- Controlled command execution with shell operators blocked, approvals for risky commands, timeout, and output limits.
- Dedicated Git status, diff, log, branch listing, branch creation, commit, push, pull, and checkout tools.
- Read-only Git operations run automatically; state-changing operations require approval.
- Dynamic tool creation (`create_and_register_tool`) and hot-reloading (`reload_tools`) with syntax verification, isolated test validation, interactive human approval, and persistent storage.
- Focused security and behavior tests.

## Phase 2: Browser, web research, and downloads

Planned:

- Add Playwright-backed browser tools in a separate module.
- Treat page content as untrusted data.
- Add URL validation, navigation/read/click/type controls, and download limits.
- Require approval for executable downloads and consequential form submissions.

## Phase 3: Desktop, clipboard, and screen control

Planned:

- Add isolated application/window controls.
- Add guarded clipboard and screenshot/screen interaction tools.
- Redact or block sensitive clipboard and screen data before external transmission.

## Phase 4: Docker and DevOps

Planned:

- Add constrained Docker, Terraform, Azure CLI, AWS CLI, and Kubernetes inspection tools.
- Require approval for operations that mutate containers, state, or infrastructure.

## Authentication foundation

Status: implemented; provider tools are still added separately.

- Authentication settings live in `config/auth.json`.
- Actual tokens are loaded from environment variables such as `GITHUB_TOKEN`.
- Tokens are never stored in the repository config or printed by the agent.
- GitHub API tools will be added only when their permission policy is defined.

## Phase 5: MCP, memory, and observability

Planned:

- Add trusted MCP discovery through the same permission layer.
- Add SQLite memory for non-sensitive user/project preferences.
- Add redacted audit and approval logs.

## Phase 6: Hardening

Planned:

- Expand security boundary tests.
- Add output-size and timeout tests.
- Review failure recovery and fail-closed behavior.
- Validate every registered tool against its permission policy.
