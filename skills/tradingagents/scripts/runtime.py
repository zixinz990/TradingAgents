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
