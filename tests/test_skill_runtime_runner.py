from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "tradingagents"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_runtime():
    return load_module(SKILL_DIR / "scripts" / "runtime.py", "skill_runtime")


def base_config(tmp_path: Path, selected_analysts: list[str] | None = None) -> dict:
    return {
        "ticker": "NVDA",
        "trade_date": "2026-05-04",
        "selected_analysts": selected_analysts or ["market", "social", "news", "fundamentals"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "output_language": "English",
        "results_dir": "skill_runs",
        "data_vendors": {
            "core_stock_apis": "yfinance",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
        },
        "tool_vendors": {},
        "data_inputs": {},
    }


def write_config(tmp_path: Path, config: dict) -> Path:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_init_run_creates_safe_report_dir_and_initial_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    config = base_config(tmp_path)
    config_path = write_config(tmp_path, config)

    state_path = runtime.init_run(config_path)
    state = read_json(state_path)

    assert state_path.resolve() == tmp_path / "skill_runs" / "NVDA_2026-05-04" / "state.json"
    assert state["company_of_interest"] == "NVDA"
    assert state["trade_date"] == "2026-05-04"
    assert state["messages"] == [{"role": "human", "content": "NVDA"}]
    assert state["market_report"] == ""
    assert state["sentiment_report"] == ""
    assert state["news_report"] == ""
    assert state["fundamentals_report"] == ""
    assert state["investment_debate_state"]["count"] == 0
    assert state["risk_debate_state"]["count"] == 0
    assert state["skill_runtime"]["step_index"] == 0
    assert state["skill_runtime"]["completed_steps"] == []
    assert Path(state["skill_runtime"]["report_dir"]).resolve() == state_path.parent.resolve()
    assert state["skill_runtime"]["step_order"][:4] == [
        "market_analyst",
        "social_media_analyst",
        "news_analyst",
        "fundamentals_analyst",
    ]


def test_init_run_rejects_invalid_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    config = base_config(tmp_path)
    config["ticker"] = "../NVDA"
    config_path = write_config(tmp_path, config)

    with pytest.raises(ValueError, match="ticker must be a safe ticker path component"):
        runtime.init_run(config_path)

    config = base_config(tmp_path)
    config["results_dir"] = str(tmp_path / "skill_runs")
    config_path = write_config(tmp_path, config)

    with pytest.raises(ValueError, match="results_dir must be a safe relative path"):
        runtime.init_run(config_path)


def test_build_step_order_matches_selected_analysts_and_round_counts(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    config["max_debate_rounds"] = 2
    config["max_risk_discuss_rounds"] = 1

    assert runtime.build_step_order(config) == [
        "market_analyst",
        "bull_researcher",
        "bear_researcher",
        "bull_researcher",
        "bear_researcher",
        "research_manager",
        "trader",
        "risk_aggressive",
        "risk_conservative",
        "risk_neutral",
        "portfolio_manager",
    ]


def test_next_step_emits_role_packet_from_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    config_path = write_config(tmp_path, config)
    state_path = runtime.init_run(config_path)

    packet_path = runtime.next_step(state_path.parent)
    packet = read_json(packet_path)

    assert packet_path == state_path.parent / "next_step.json"
    assert packet["role_id"] == "market_analyst"
    assert packet["display_name"] == "Market Analyst"
    assert packet["source_path"] == "tradingagents/agents/analysts/market_analyst.py"
    assert packet["report_path"] == "1_analysts/market.md"
    assert packet["output_path"] == str(state_path.parent / "1_analysts" / "market.md")
    assert packet["allowed_tools"] == ["get_stock_data", "get_indicators"]
    assert packet["required_markers"] == []
    assert packet["input_state"]["company_of_interest"] == "NVDA"
    assert packet["input_state"]["trade_date"] == "2026-05-04"
    assert packet["tool_request_path"] == str(state_path.parent / "tool_request.json")


def test_next_step_emits_required_markers_for_structured_roles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    config_path = write_config(tmp_path, config)
    state_path = runtime.init_run(config_path)
    state = read_json(state_path)

    expected = {
        "research_manager": ["**Recommendation**:"],
        "trader": ["**Action**:", "FINAL TRANSACTION PROPOSAL"],
        "portfolio_manager": [
            "**Rating**:",
            "**Executive Summary**:",
            "**Investment Thesis**:",
        ],
    }

    for role_id, markers in expected.items():
        state["skill_runtime"]["step_index"] = state["skill_runtime"]["step_order"].index(role_id)
        state_path.write_text(json.dumps(state), encoding="utf-8")

        packet_path = runtime.next_step(state_path.parent)
        packet = read_json(packet_path)

        assert packet["role_id"] == role_id
        assert packet["required_markers"] == markers


def test_next_step_reports_completion_when_all_steps_applied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    config_path = write_config(tmp_path, config)
    state_path = runtime.init_run(config_path)
    state = read_json(state_path)
    state["skill_runtime"]["step_index"] = len(state["skill_runtime"]["step_order"])
    state["skill_runtime"]["status"] = "ready_to_finalize"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    packet_path = runtime.next_step(state_path.parent)
    packet = read_json(packet_path)

    assert packet["status"] == "complete"
    assert packet["message"] == "all role steps have been applied"
