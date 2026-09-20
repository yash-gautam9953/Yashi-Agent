import json
import re
from pathlib import Path
from typing import Callable


Approval = Callable[[str], bool]
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def request_new_tool(
    workspace: Path,
    approve: Approval,
    name: str,
    capability: str,
    reason: str,
    risk_level: str = "unknown",
    suggested_inputs: str = "",
) -> str:
    if not _TOOL_NAME.fullmatch(name):
        raise ValueError("Tool name must be lowercase snake_case")
    if not capability.strip() or len(capability) > 1000:
        raise ValueError("Capability must be between 1 and 1000 characters")
    if not reason.strip() or len(reason) > 1000:
        raise ValueError("Reason must be between 1 and 1000 characters")
    if risk_level not in {"safe", "approval", "blocked", "unknown"}:
        raise ValueError("Invalid risk level")

    proposal_dir = workspace / "tool_proposals"
    proposal_path = proposal_dir / f"{name}.json"
    if not approve(
        f"Create tool proposal '{name}'?\n"
        f"Reason: {reason}\n"
        "The proposal will be reviewed before activation.\n"
        "Allow?"
    ):
        return json.dumps({
            "ok": False,
            "status": "denied",
            "name": name,
        })

    proposal_dir.mkdir(exist_ok=True)
    proposal = {
        "name": name,
        "capability": capability,
        "reason": reason,
        "risk_level": risk_level,
        "suggested_inputs": suggested_inputs,
        "status": "review_required",
    }
    proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    return json.dumps({
        "ok": True,
        "status": "review_required",
        "proposal_path": str(proposal_path.relative_to(workspace)),
        "message": "Tool proposal created; it is not active yet.",
    })
