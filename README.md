# Yashi Agent

A minimal Azure OpenAI personal agent with one model-facing tool:
`create_and_register_tool`.

## How it works

1. Start a session with `python main.py`.
2. Give the agent a task.
3. If the capability is missing, the model generates a narrowly scoped Python tool.
4. The tool must pass syntax and optional test validation.
5. The console asks for explicit approval and shows a code preview.
6. After approval, the tool is saved in `custom_tools/`, registered in the current session, and used for the task.

The model does not receive filesystem, Git, shell, browser, or desktop tools by default. Those capabilities can only exist after an approved custom tool is created.

## Configuration

Copy `.env.example` to `.env` and set the Azure OpenAI endpoint, deployment, and API key. Never commit `.env` or credentials.

## Run

```powershell
python main.py
```

Use `help` for a short prompt guide and `exit` to end the session.

## Tests

```powershell
python -m unittest tests.test_custom_tools -v
```

Tests run offline and do not call the LLM or network.
