"""Deterministic runtime helpers for TradingAgents skill runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ROOT = SKILL_DIR.parent.parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_config import load_config, validate_config  # noqa: E402


STATE_FILENAME = "state.json"
PACKET_FILENAME = "next_step.json"

ANALYST_ROLE_BY_CONFIG = {
    "market": "market_analyst",
    "social": "social_media_analyst",
    "news": "news_analyst",
    "fundamentals": "fundamentals_analyst",
}


def read_json(path: Path | str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path | str, payload: Any) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def load_validated_config(config_path: Path | str) -> dict[str, Any]:
    config = load_config(Path(config_path))
    errors = validate_config(config)
    if errors:
        raise ValueError("; ".join(errors))
    return config


def report_dir_for(config: dict[str, Any]) -> Path:
    safe_ticker = safe_ticker_component(config["ticker"])
    return Path(config["results_dir"]) / f"{safe_ticker}_{config['trade_date']}"


def build_step_order(config: dict[str, Any]) -> list[str]:
    analyst_steps = [
        ANALYST_ROLE_BY_CONFIG[analyst]
        for analyst in config["selected_analysts"]
    ]
    debate_steps = ["bull_researcher", "bear_researcher"] * config["max_debate_rounds"]
    risk_steps = [
        "risk_aggressive",
        "risk_conservative",
        "risk_neutral",
    ] * config["max_risk_discuss_rounds"]
    return (
        analyst_steps
        + debate_steps
        + ["research_manager", "trader"]
        + risk_steps
        + ["portfolio_manager"]
    )


def initial_state(config: dict[str, Any], report_dir: Path) -> dict[str, Any]:
    return {
        "messages": [{"role": "human", "content": config["ticker"]}],
        "company_of_interest": config["ticker"],
        "trade_date": config["trade_date"],
        "past_context": config.get("past_context", ""),
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_plan": "",
        "trader_investment_plan": "",
        "final_trade_decision": "",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "skill_runtime": {
            "config": config,
            "report_dir": str(report_dir),
            "step_order": build_step_order(config),
            "step_index": 0,
            "completed_steps": [],
            "tool_transcripts": [],
            "status": "in_progress",
        },
    }


def state_path_for(report_dir: Path | str) -> Path:
    return Path(report_dir) / STATE_FILENAME


def load_state(report_dir: Path | str) -> dict[str, Any]:
    return read_json(state_path_for(report_dir))


def save_state(report_dir: Path | str, state: dict[str, Any]) -> Path:
    return write_json(state_path_for(report_dir), state)


def init_run(config_path: Path | str) -> Path:
    config = load_validated_config(config_path)
    report_dir = report_dir_for(config)
    report_dir.mkdir(parents=True, exist_ok=True)
    state = initial_state(config, report_dir)
    return save_state(report_dir, state)


REQUIRED_MARKERS = {
    "research_manager": ["**Recommendation**:"],
    "trader": ["**Action**:", "FINAL TRANSACTION PROPOSAL"],
    "portfolio_manager": [
        "**Rating**:",
        "**Executive Summary**:",
        "**Investment Thesis**:",
    ],
}


def load_prompt_manifest() -> dict[str, Any]:
    return read_json(SKILL_DIR / "prompt_manifest.json")


def roles_by_id() -> dict[str, dict[str, Any]]:
    manifest = load_prompt_manifest()
    return {role["id"]: role for role in manifest["roles"]}


def current_role_id(state: dict[str, Any]) -> str | None:
    runtime = state["skill_runtime"]
    step_index = runtime["step_index"]
    step_order = runtime["step_order"]
    if step_index >= len(step_order):
        return None
    return step_order[step_index]


def role_required_markers(role_id: str) -> list[str]:
    return REQUIRED_MARKERS.get(role_id, [])


def packet_input_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_of_interest": state["company_of_interest"],
        "trade_date": state["trade_date"],
        "market_report": state["market_report"],
        "sentiment_report": state["sentiment_report"],
        "news_report": state["news_report"],
        "fundamentals_report": state["fundamentals_report"],
        "investment_debate_state": state["investment_debate_state"],
        "investment_plan": state["investment_plan"],
        "trader_investment_plan": state["trader_investment_plan"],
        "risk_debate_state": state["risk_debate_state"],
        "final_trade_decision": state["final_trade_decision"],
        "past_context": state.get("past_context", ""),
    }


def build_role_packet(state: dict[str, Any], role_id: str) -> dict[str, Any]:
    role = roles_by_id()[role_id]
    report_dir = Path(state["skill_runtime"]["report_dir"])
    output_path = report_dir / role["report_path"]
    return {
        "status": "role_ready",
        "role_id": role_id,
        "display_name": role["display_name"],
        "source_path": role["source_path"],
        "report_path": role["report_path"],
        "output_path": str(output_path),
        "allowed_tools": role["allowed_tools"],
        "required_markers": role_required_markers(role_id),
        "input_state": packet_input_state(state),
        "tool_request_path": str(report_dir / "tool_request.json"),
        "instructions": (
            "Read source_path from the repository root, preserve the role intent, "
            "use only this packet's input_state and allowed_tools, then write "
            "the final role report to output_path."
        ),
    }


def next_step(report_dir: Path | str) -> Path:
    state = load_state(report_dir)
    role_id = current_role_id(state)
    packet_path = Path(report_dir) / PACKET_FILENAME
    if role_id is None:
        return write_json(
            packet_path,
            {
                "status": "complete",
                "message": "all role steps have been applied",
            },
        )
    return write_json(packet_path, build_role_packet(state, role_id))


ANALYST_OUTPUT_FIELDS = {
    "market_analyst": "market_report",
    "social_media_analyst": "sentiment_report",
    "news_analyst": "news_report",
    "fundamentals_analyst": "fundamentals_report",
}

INVESTMENT_DEBATE_ROLES = {
    "bull_researcher": ("Bull Analyst", "bull_history"),
    "bear_researcher": ("Bear Analyst", "bear_history"),
}

RISK_DEBATE_ROLES = {
    "risk_aggressive": (
        "Aggressive Analyst",
        "aggressive_history",
        "current_aggressive_response",
        "Aggressive",
    ),
    "risk_conservative": (
        "Conservative Analyst",
        "conservative_history",
        "current_conservative_response",
        "Conservative",
    ),
    "risk_neutral": (
        "Neutral Analyst",
        "neutral_history",
        "current_neutral_response",
        "Neutral",
    ),
}


def normalize_speaker_content(prefix: str, content: str) -> str:
    stripped = content.strip()
    if stripped.startswith(f"{prefix}:"):
        return stripped
    return f"{prefix}: {stripped}"


def assert_required_markers(role_id: str, relative_path: str, content: str) -> None:
    for marker in role_required_markers(role_id):
        if marker not in content:
            raise ValueError(f"{relative_path} missing required marker {marker}")
    if role_id == "trader":
        import re

        if re.search(r"^FINAL TRANSACTION PROPOSAL: \*\*(BUY|HOLD|SELL)\*\*$", content, re.MULTILINE) is None:
            raise ValueError(f"{relative_path} missing valid final transaction proposal")


def role_report_content(report_dir: Path, role: dict[str, Any]) -> str:
    report_path = report_dir / role["report_path"]
    if not report_path.exists():
        raise FileNotFoundError(f"missing required report fragment: {role['report_path']}")
    return report_path.read_text(encoding="utf-8").strip()


def apply_investment_debate(state: dict[str, Any], role_id: str, content: str) -> None:
    prefix, history_key = INVESTMENT_DEBATE_ROLES[role_id]
    argument = normalize_speaker_content(prefix, content)
    debate = state["investment_debate_state"]
    debate["history"] = debate.get("history", "") + "\n" + argument
    debate[history_key] = debate.get(history_key, "") + "\n" + argument
    debate["current_response"] = argument
    debate["count"] = debate["count"] + 1


def apply_risk_debate(state: dict[str, Any], role_id: str, content: str) -> None:
    prefix, history_key, current_key, latest_speaker = RISK_DEBATE_ROLES[role_id]
    argument = normalize_speaker_content(prefix, content)
    debate = state["risk_debate_state"]
    debate["history"] = debate.get("history", "") + "\n" + argument
    debate[history_key] = debate.get(history_key, "") + "\n" + argument
    debate[current_key] = argument
    debate["latest_speaker"] = latest_speaker
    debate["count"] = debate["count"] + 1


def apply_role_content(state: dict[str, Any], role_id: str, content: str) -> None:
    if role_id in ANALYST_OUTPUT_FIELDS:
        state[ANALYST_OUTPUT_FIELDS[role_id]] = content
    elif role_id in INVESTMENT_DEBATE_ROLES:
        apply_investment_debate(state, role_id, content)
    elif role_id == "research_manager":
        debate = state["investment_debate_state"]
        debate["judge_decision"] = content
        debate["current_response"] = content
        state["investment_plan"] = content
    elif role_id == "trader":
        state["trader_investment_plan"] = content
        state["sender"] = "Trader"
    elif role_id in RISK_DEBATE_ROLES:
        apply_risk_debate(state, role_id, content)
    elif role_id == "portfolio_manager":
        debate = state["risk_debate_state"]
        debate["judge_decision"] = content
        debate["latest_speaker"] = "Judge"
        state["final_trade_decision"] = content
    else:
        raise ValueError(f"unknown role id: {role_id}")


def advance_runtime(state: dict[str, Any], role_id: str) -> None:
    runtime = state["skill_runtime"]
    runtime["completed_steps"].append(role_id)
    runtime["step_index"] = runtime["step_index"] + 1
    if runtime["step_index"] >= len(runtime["step_order"]):
        runtime["status"] = "ready_to_finalize"


def apply_step(report_dir: Path | str, role_id: str | None = None) -> Path:
    report_dir = Path(report_dir)
    state = load_state(report_dir)
    expected_role_id = current_role_id(state)
    if expected_role_id is None:
        raise ValueError("all role steps have already been applied")
    if role_id is not None and role_id != expected_role_id:
        raise ValueError(
            f"cannot apply role {role_id} while current role is {expected_role_id}"
        )

    role = roles_by_id()[expected_role_id]
    content = role_report_content(report_dir, role)
    assert_required_markers(expected_role_id, role["report_path"], content)
    apply_role_content(state, expected_role_id, content)
    advance_runtime(state, expected_role_id)
    return save_state(report_dir, state)


from tradingagents.agents.utils.agent_utils import (  # noqa: E402
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_indicators,
    get_income_statement,
    get_insider_transactions,
    get_news,
    get_stock_data,
)
from tradingagents.dataflows.config import set_config  # noqa: E402


TOOL_REGISTRY = {
    "get_stock_data": get_stock_data,
    "get_indicators": get_indicators,
    "get_fundamentals": get_fundamentals,
    "get_balance_sheet": get_balance_sheet,
    "get_cashflow": get_cashflow,
    "get_income_statement": get_income_statement,
    "get_news": get_news,
    "get_global_news": get_global_news,
    "get_insider_transactions": get_insider_transactions,
}


def load_tool_request(path: Path | str) -> dict[str, Any]:
    request = read_json(path)
    if not isinstance(request, dict):
        raise ValueError("tool_request.json must contain a JSON object")
    for key in ("role_id", "tool", "arguments"):
        if key not in request:
            raise ValueError(f"tool_request.json missing required field {key}")
    if not isinstance(request["role_id"], str):
        raise ValueError("tool_request.json role_id must be a string")
    if not isinstance(request["tool"], str):
        raise ValueError("tool_request.json tool must be a string")
    if not isinstance(request["arguments"], dict):
        raise ValueError("tool_request.json arguments must be an object")
    return request


def validate_tool_request(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    expected_role_id = current_role_id(state)
    if expected_role_id is None:
        raise ValueError("no current role can execute tool requests")
    if request["role_id"] != expected_role_id:
        raise ValueError(
            f"tool request role {request['role_id']} does not match current role {expected_role_id}"
        )
    role = roles_by_id()[expected_role_id]
    tool_name = request["tool"]
    if tool_name not in role["allowed_tools"]:
        raise ValueError(f"tool {tool_name} is not allowed for role {expected_role_id}")
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"tool {tool_name} is not registered")
    for argument_name in ("ticker", "symbol"):
        if argument_name in request["arguments"]:
            try:
                safe_ticker_component(request["arguments"][argument_name])
            except ValueError as exc:
                raise ValueError(
                    f"{argument_name} must be a safe ticker path component"
                ) from exc
    return role


def invoke_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    tool = TOOL_REGISTRY[tool_name]
    if hasattr(tool, "invoke"):
        result = tool.invoke(arguments)
    else:
        result = tool(**arguments)
    return str(result)


def next_tool_transcript_path(report_dir: Path, state: dict[str, Any], role_id: str, tool_name: str) -> Path:
    index = len(state["skill_runtime"]["tool_transcripts"]) + 1
    safe_name = f"{index:03d}_{role_id}_{tool_name}.json"
    return report_dir / "tool_transcripts" / safe_name


def run_tool_request(report_dir: Path | str, request_path: Path | str | None = None) -> Path:
    report_dir = Path(report_dir)
    request_path = Path(request_path) if request_path is not None else report_dir / "tool_request.json"
    state = load_state(report_dir)
    request = load_tool_request(request_path)
    validate_tool_request(state, request)
    set_config(state["skill_runtime"]["config"])
    result = invoke_tool(request["tool"], request["arguments"])
    transcript_path = next_tool_transcript_path(
        report_dir,
        state,
        request["role_id"],
        request["tool"],
    )
    transcript = {
        "role_id": request["role_id"],
        "tool": request["tool"],
        "arguments": request["arguments"],
        "result": result,
    }
    write_json(transcript_path, transcript)
    state["skill_runtime"]["tool_transcripts"].append(str(transcript_path))
    save_state(report_dir, state)
    return transcript_path
