# TradingAgents Skill Runtime Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic skill-runner layer that makes TradingAgents skill runs preserve original LangGraph-style ordering, state updates, tool gating, structured markers, final artifacts, and rating extraction while still using the host CLI agent as the model runtime.

**Architecture:** Create a pure Python runtime module for state-machine logic and a small argparse wrapper for CLI subcommands. The runtime reads existing skill manifests and authoritative source paths, emits one role packet at a time, applies role reports into an AgentState-like JSON artifact, validates tool requests through allowlists, finalizes reports, and optionally compares a saved API baseline. Existing prompts, LangGraph code, and LLM provider clients stay untouched.

**Tech Stack:** Python 3.10+, pytest, argparse, JSON files, existing `skills/tradingagents` helper scripts, existing `tradingagents.agents.utils.rating.parse_rating`, existing `tradingagents.dataflows` routing.

---

## File Structure

- Create: `skills/tradingagents/scripts/runtime.py`
  - Owns deterministic skill-run state, role order, role packets, tool request validation, state mutation, finalization, and parity comparison.
- Create: `skills/tradingagents/scripts/skill_runner.py`
  - Thin argparse CLI over `runtime.py` with subcommands: `init-run`, `next-step`, `run-tool-request`, `apply-step`, `finalize-run`, and `parity-check`.
- Create: `tests/test_skill_runtime_runner.py`
  - Unit and fixture-based end-to-end coverage for runtime helpers and CLI behavior.
- Modify: `skills/tradingagents/SKILL.md`
  - Replace the manual-only workflow with deterministic runner instructions while keeping source-of-truth constraints.
- Modify: `skills/tradingagents/README.md`
  - Document the new runner command sequence and generated artifacts.
- Modify: `tests/test_skill_version_artifacts.py`
  - Extend artifact coverage so the skill package requires `runtime.py`, `skill_runner.py`, and runner documentation.

---

### Task 1: Add Initial State Runtime

**Files:**
- Create: `skills/tradingagents/scripts/runtime.py`
- Create: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing initial-state tests**

Create `tests/test_skill_runtime_runner.py` with this content:

```python
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
        "results_dir": str(tmp_path / "skill_runs"),
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


def test_init_run_creates_safe_report_dir_and_initial_state(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path)
    config_path = write_config(tmp_path, config)

    state_path = runtime.init_run(config_path)
    state = read_json(state_path)

    assert state_path == tmp_path / "skill_runs" / "NVDA_2026-05-04" / "state.json"
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
    assert state["skill_runtime"]["report_dir"] == str(state_path.parent)
    assert state["skill_runtime"]["step_order"][:4] == [
        "market_analyst",
        "social_media_analyst",
        "news_analyst",
        "fundamentals_analyst",
    ]


def test_init_run_rejects_invalid_config(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path)
    config["ticker"] = "../NVDA"
    config_path = write_config(tmp_path, config)

    with pytest.raises(ValueError, match="ticker must be a safe ticker path component"):
        runtime.init_run(config_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_init_run_creates_safe_report_dir_and_initial_state tests/test_skill_runtime_runner.py::test_init_run_rejects_invalid_config -v
```

Expected: FAIL because `skills/tradingagents/scripts/runtime.py` does not exist.

- [ ] **Step 3: Add the runtime initial-state implementation**

Create `skills/tradingagents/scripts/runtime.py` with this content:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_init_run_creates_safe_report_dir_and_initial_state tests/test_skill_runtime_runner.py::test_init_run_rejects_invalid_config -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add skills/tradingagents/scripts/runtime.py tests/test_skill_runtime_runner.py
git commit -m "feat: add skill runtime state initialization" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Add Step Order and Role Packet Generation

**Files:**
- Modify: `skills/tradingagents/scripts/runtime.py`
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing role-packet tests**

Append these tests to `tests/test_skill_runtime_runner.py`:

```python
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


def test_next_step_emits_role_packet_from_manifest(tmp_path):
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


def test_next_step_reports_completion_when_all_steps_applied(tmp_path):
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_build_step_order_matches_selected_analysts_and_round_counts tests/test_skill_runtime_runner.py::test_next_step_emits_role_packet_from_manifest tests/test_skill_runtime_runner.py::test_next_step_reports_completion_when_all_steps_applied -v
```

Expected: FAIL because `next_step` is not defined.

- [ ] **Step 3: Add role metadata and `next_step`**

Append this code to `skills/tradingagents/scripts/runtime.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_build_step_order_matches_selected_analysts_and_round_counts tests/test_skill_runtime_runner.py::test_next_step_emits_role_packet_from_manifest tests/test_skill_runtime_runner.py::test_next_step_reports_completion_when_all_steps_applied -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add skills/tradingagents/scripts/runtime.py tests/test_skill_runtime_runner.py
git commit -m "feat: emit tradingagents skill role packets" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Apply Role Reports Into State

**Files:**
- Modify: `skills/tradingagents/scripts/runtime.py`
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing apply-step tests**

Append these tests to `tests/test_skill_runtime_runner.py`:

```python
def write_role_report(report_dir: Path, relative_path: str, content: str) -> Path:
    output_path = report_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def test_apply_step_updates_analyst_report_and_advances_state(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    write_role_report(report_dir, "1_analysts/market.md", "market report")

    runtime.apply_step(report_dir)
    state = read_json(state_path)

    assert state["market_report"] == "market report"
    assert state["skill_runtime"]["step_index"] == 1
    assert state["skill_runtime"]["completed_steps"] == ["market_analyst"]


def test_apply_step_rejects_missing_required_marker(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    state = read_json(state_path)
    manager_index = state["skill_runtime"]["step_order"].index("research_manager")
    state["skill_runtime"]["step_index"] = manager_index
    state_path.write_text(json.dumps(state), encoding="utf-8")
    write_role_report(report_dir, "2_research/manager.md", "manager without marker")

    with pytest.raises(ValueError, match="2_research/manager.md missing required marker"):
        runtime.apply_step(report_dir)


def test_apply_step_updates_debate_and_risk_counters(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    state = read_json(state_path)

    state["skill_runtime"]["step_index"] = state["skill_runtime"]["step_order"].index("bull_researcher")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    write_role_report(report_dir, "2_research/bull.md", "Bull case text")
    runtime.apply_step(report_dir)
    state = read_json(state_path)
    assert state["investment_debate_state"]["count"] == 1
    assert state["investment_debate_state"]["current_response"] == "Bull Analyst: Bull case text"
    assert "Bull Analyst: Bull case text" in state["investment_debate_state"]["bull_history"]

    state["skill_runtime"]["step_index"] = state["skill_runtime"]["step_order"].index("risk_aggressive")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    write_role_report(report_dir, "4_risk/aggressive.md", "Aggressive risk text")
    runtime.apply_step(report_dir)
    state = read_json(state_path)
    assert state["risk_debate_state"]["count"] == 1
    assert state["risk_debate_state"]["latest_speaker"] == "Aggressive"
    assert state["risk_debate_state"]["current_aggressive_response"] == "Aggressive Analyst: Aggressive risk text"


def test_apply_step_rejects_unexpected_role_id(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    write_role_report(report_dir, "1_analysts/market.md", "market report")

    with pytest.raises(ValueError, match="cannot apply role trader while current role is market_analyst"):
        runtime.apply_step(report_dir, role_id="trader")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_apply_step_updates_analyst_report_and_advances_state tests/test_skill_runtime_runner.py::test_apply_step_rejects_missing_required_marker tests/test_skill_runtime_runner.py::test_apply_step_updates_debate_and_risk_counters tests/test_skill_runtime_runner.py::test_apply_step_rejects_unexpected_role_id -v
```

Expected: FAIL because `apply_step` is not defined.

- [ ] **Step 3: Add apply-step implementation**

Append this code to `skills/tradingagents/scripts/runtime.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_apply_step_updates_analyst_report_and_advances_state tests/test_skill_runtime_runner.py::test_apply_step_rejects_missing_required_marker tests/test_skill_runtime_runner.py::test_apply_step_updates_debate_and_risk_counters tests/test_skill_runtime_runner.py::test_apply_step_rejects_unexpected_role_id -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add skills/tradingagents/scripts/runtime.py tests/test_skill_runtime_runner.py
git commit -m "feat: apply skill role reports to state" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Add Deterministic Tool Request Execution

**Files:**
- Modify: `skills/tradingagents/scripts/runtime.py`
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing tool-request tests**

Append these tests to `tests/test_skill_runtime_runner.py`:

```python
def test_run_tool_request_executes_only_allowed_tool_and_records_transcript(tmp_path, monkeypatch):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent

    class FakeTool:
        def invoke(self, arguments):
            return f"tool output for {arguments['symbol']}"

    monkeypatch.setitem(runtime.TOOL_REGISTRY, "get_stock_data", FakeTool())
    request_path = report_dir / "tool_request.json"
    request_path.write_text(
        json.dumps(
            {
                "role_id": "market_analyst",
                "tool": "get_stock_data",
                "arguments": {
                    "symbol": "NVDA",
                    "start_date": "2026-04-01",
                    "end_date": "2026-05-04",
                },
            }
        ),
        encoding="utf-8",
    )

    transcript_path = runtime.run_tool_request(report_dir)
    transcript = read_json(transcript_path)
    state = read_json(state_path)

    assert transcript["role_id"] == "market_analyst"
    assert transcript["tool"] == "get_stock_data"
    assert transcript["result"] == "tool output for NVDA"
    assert state["skill_runtime"]["tool_transcripts"] == [str(transcript_path)]


def test_run_tool_request_rejects_disallowed_tool(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    (report_dir / "tool_request.json").write_text(
        json.dumps(
            {
                "role_id": "market_analyst",
                "tool": "get_news",
                "arguments": {
                    "ticker": "NVDA",
                    "start_date": "2026-04-01",
                    "end_date": "2026-05-04",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="tool get_news is not allowed for role market_analyst"):
        runtime.run_tool_request(report_dir)


def test_run_tool_request_rejects_unsafe_symbol_argument(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    (report_dir / "tool_request.json").write_text(
        json.dumps(
            {
                "role_id": "market_analyst",
                "tool": "get_stock_data",
                "arguments": {
                    "symbol": "../NVDA",
                    "start_date": "2026-04-01",
                    "end_date": "2026-05-04",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="symbol must be a safe ticker path component"):
        runtime.run_tool_request(report_dir)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_run_tool_request_executes_only_allowed_tool_and_records_transcript tests/test_skill_runtime_runner.py::test_run_tool_request_rejects_disallowed_tool tests/test_skill_runtime_runner.py::test_run_tool_request_rejects_unsafe_symbol_argument -v
```

Expected: FAIL because `TOOL_REGISTRY` and `run_tool_request` are not defined.

- [ ] **Step 3: Add tool registry and request execution**

Append this code to `skills/tradingagents/scripts/runtime.py`:

```python
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
    if not isinstance(request["arguments"], dict):
        raise ValueError("tool_request.json arguments must be an object")
    return request


def validate_tool_request(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    expected_role_id = current_role_id(state)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_run_tool_request_executes_only_allowed_tool_and_records_transcript tests/test_skill_runtime_runner.py::test_run_tool_request_rejects_disallowed_tool tests/test_skill_runtime_runner.py::test_run_tool_request_rejects_unsafe_symbol_argument -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add skills/tradingagents/scripts/runtime.py tests/test_skill_runtime_runner.py
git commit -m "feat: gate tradingagents skill tool requests" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Finalize Runs and Compare Parity Baselines

**Files:**
- Modify: `skills/tradingagents/scripts/runtime.py`
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing finalization and parity tests**

Append these tests to `tests/test_skill_runtime_runner.py`:

```python
def write_all_reports_for_one_analyst_run(report_dir: Path) -> None:
    fragments = {
        "1_analysts/market.md": "market report",
        "2_research/bull.md": "bull report",
        "2_research/bear.md": "bear report",
        "2_research/manager.md": "**Recommendation**: Buy",
        "3_trading/trader.md": "**Action**: Buy\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "4_risk/aggressive.md": "aggressive risk",
        "4_risk/conservative.md": "conservative risk",
        "4_risk/neutral.md": "neutral risk",
        "5_portfolio/decision.md": (
            "**Rating**: Overweight\n"
            "**Executive Summary**: summary\n"
            "**Investment Thesis**: thesis"
        ),
    }
    for relative_path, content in fragments.items():
        write_role_report(report_dir, relative_path, content)


def apply_all_steps(runtime, report_dir: Path) -> None:
    while True:
        state = read_json(report_dir / "state.json")
        role_id = runtime.current_role_id(state)
        if role_id is None:
            break
        runtime.apply_step(report_dir)


def test_finalize_run_writes_complete_report_state_log_and_rating(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent
    write_all_reports_for_one_analyst_run(report_dir)
    apply_all_steps(runtime, report_dir)

    result = runtime.finalize_run(report_dir)

    assert Path(result["complete_report"]).exists()
    assert Path(result["state_log"]).exists()
    assert result["rating"] == "Overweight"
    log = read_json(Path(result["state_log"]))
    assert log["company_of_interest"] == "NVDA"
    assert log["market_report"] == "market report"
    assert log["trader_investment_decision"].startswith("**Action**: Buy")
    assert log["final_trade_decision"].startswith("**Rating**: Overweight")


def test_finalize_run_rejects_incomplete_workflow(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))

    with pytest.raises(ValueError, match="cannot finalize before all role steps are applied"):
        runtime.finalize_run(state_path.parent)


def test_parity_check_reports_structural_differences(tmp_path):
    runtime = load_runtime()
    api_state = tmp_path / "api.json"
    skill_state = tmp_path / "skill.json"
    api_state.write_text(json.dumps({"final_trade_decision": "**Rating**: Buy"}), encoding="utf-8")
    skill_state.write_text(json.dumps({"final_trade_decision": "**Rating**: Sell"}), encoding="utf-8")

    result = runtime.parity_check(api_state, skill_state)

    assert result["passed"] is False
    assert "final_trade_decision differs" in result["differences"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_finalize_run_writes_complete_report_state_log_and_rating tests/test_skill_runtime_runner.py::test_finalize_run_rejects_incomplete_workflow tests/test_skill_runtime_runner.py::test_parity_check_reports_structural_differences -v
```

Expected: FAIL because `finalize_run` and `parity_check` are not defined.

- [ ] **Step 3: Add finalization and parity comparison**

Append this code to `skills/tradingagents/scripts/runtime.py`:

```python
from assemble_report import assemble_report  # noqa: E402
from tradingagents.agents.utils.rating import parse_rating  # noqa: E402


def full_state_log_payload(state: dict[str, Any]) -> dict[str, Any]:
    investment_debate = state["investment_debate_state"]
    risk_debate = state["risk_debate_state"]
    return {
        "company_of_interest": state["company_of_interest"],
        "trade_date": state["trade_date"],
        "market_report": state["market_report"],
        "sentiment_report": state["sentiment_report"],
        "news_report": state["news_report"],
        "fundamentals_report": state["fundamentals_report"],
        "investment_debate_state": {
            "bull_history": investment_debate["bull_history"],
            "bear_history": investment_debate["bear_history"],
            "history": investment_debate["history"],
            "current_response": investment_debate["current_response"],
            "judge_decision": investment_debate["judge_decision"],
        },
        "trader_investment_decision": state["trader_investment_plan"],
        "risk_debate_state": {
            "aggressive_history": risk_debate["aggressive_history"],
            "conservative_history": risk_debate["conservative_history"],
            "neutral_history": risk_debate["neutral_history"],
            "history": risk_debate["history"],
            "judge_decision": risk_debate["judge_decision"],
        },
        "investment_plan": state["investment_plan"],
        "final_trade_decision": state["final_trade_decision"],
    }


def ensure_workflow_complete(state: dict[str, Any]) -> None:
    runtime = state["skill_runtime"]
    if runtime["step_index"] < len(runtime["step_order"]):
        raise ValueError("cannot finalize before all role steps are applied")


def write_full_state_log(report_dir: Path, state: dict[str, Any]) -> Path:
    output_dir = report_dir / "TradingAgentsStrategy_logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"full_states_log_{state['trade_date']}.json"
    return write_json(output_path, full_state_log_payload(state))


def finalize_run(report_dir: Path | str) -> dict[str, str]:
    report_dir = Path(report_dir)
    state = load_state(report_dir)
    ensure_workflow_complete(state)
    config = state["skill_runtime"]["config"]
    complete_report = assemble_report(
        report_dir,
        selected_analysts=config["selected_analysts"],
        results_dir=config["results_dir"],
    )
    state_log = write_full_state_log(report_dir, state)
    rating = parse_rating(state["final_trade_decision"])
    state["skill_runtime"]["status"] = "completed"
    state["skill_runtime"]["complete_report"] = str(complete_report)
    state["skill_runtime"]["state_log"] = str(state_log)
    state["skill_runtime"]["rating"] = rating
    save_state(report_dir, state)
    return {
        "complete_report": str(complete_report),
        "state_log": str(state_log),
        "rating": rating,
    }


def parity_check(api_state_path: Path | str, skill_state_path: Path | str) -> dict[str, Any]:
    api_state = read_json(api_state_path)
    skill_state = read_json(skill_state_path)
    differences: list[str] = []
    comparable_fields = [
        "company_of_interest",
        "trade_date",
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "investment_plan",
        "trader_investment_decision",
        "final_trade_decision",
    ]
    for field in comparable_fields:
        if field in api_state and field in skill_state and api_state[field] != skill_state[field]:
            differences.append(f"{field} differs")
        elif field in api_state and field not in skill_state:
            differences.append(f"{field} missing from skill state")
    for nested_field in ("investment_debate_state", "risk_debate_state"):
        if nested_field in api_state and nested_field not in skill_state:
            differences.append(f"{nested_field} missing from skill state")
    return {
        "passed": not differences,
        "differences": differences,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_finalize_run_writes_complete_report_state_log_and_rating tests/test_skill_runtime_runner.py::test_finalize_run_rejects_incomplete_workflow tests/test_skill_runtime_runner.py::test_parity_check_reports_structural_differences -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add skills/tradingagents/scripts/runtime.py tests/test_skill_runtime_runner.py
git commit -m "feat: finalize tradingagents skill runs" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Add CLI Wrapper

**Files:**
- Create: `skills/tradingagents/scripts/skill_runner.py`
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the failing CLI test**

Append this test to `tests/test_skill_runtime_runner.py`:

```python
def test_skill_runner_cli_init_and_next_step(tmp_path):
    import subprocess

    config = base_config(tmp_path, selected_analysts=["market"])
    config_path = write_config(tmp_path, config)
    script = SKILL_DIR / "scripts" / "skill_runner.py"

    init_result = subprocess.run(
        ["python", str(script), "init-run", str(config_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    state_path = Path(init_result.stdout.strip())
    assert state_path.exists()

    next_result = subprocess.run(
        ["python", str(script), "next-step", str(state_path.parent)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    packet_path = Path(next_result.stdout.strip())
    packet = read_json(packet_path)
    assert packet["role_id"] == "market_analyst"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_skill_runner_cli_init_and_next_step -v
```

Expected: FAIL because `skill_runner.py` does not exist.

- [ ] **Step 3: Add argparse CLI wrapper**

Create `skills/tradingagents/scripts/skill_runner.py` with this content:

```python
"""Command-line wrapper for deterministic TradingAgents skill runtime helpers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-run", help="Create a skill run state directory")
    init_parser.add_argument("config", type=Path)

    next_parser = subparsers.add_parser("next-step", help="Emit the next role packet")
    next_parser.add_argument("report_dir", type=Path)

    tool_parser = subparsers.add_parser("run-tool-request", help="Execute a validated role tool request")
    tool_parser.add_argument("report_dir", type=Path)
    tool_parser.add_argument("--request", type=Path)

    apply_parser = subparsers.add_parser("apply-step", help="Apply the current role report into state")
    apply_parser.add_argument("report_dir", type=Path)
    apply_parser.add_argument("--role-id")

    finalize_parser = subparsers.add_parser("finalize-run", help="Assemble final artifacts")
    finalize_parser.add_argument("report_dir", type=Path)

    parity_parser = subparsers.add_parser("parity-check", help="Compare API and skill state logs")
    parity_parser.add_argument("api_state", type=Path)
    parity_parser.add_argument("skill_state", type=Path)

    args = parser.parse_args(argv)

    if args.command == "init-run":
        print(runtime.init_run(args.config))
    elif args.command == "next-step":
        print(runtime.next_step(args.report_dir))
    elif args.command == "run-tool-request":
        print(runtime.run_tool_request(args.report_dir, request_path=args.request))
    elif args.command == "apply-step":
        print(runtime.apply_step(args.report_dir, role_id=args.role_id))
    elif args.command == "finalize-run":
        print(json.dumps(runtime.finalize_run(args.report_dir), indent=2))
    elif args.command == "parity-check":
        print(json.dumps(runtime.parity_check(args.api_state, args.skill_state), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_skill_runner_cli_init_and_next_step -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add skills/tradingagents/scripts/skill_runner.py tests/test_skill_runtime_runner.py
git commit -m "feat: add tradingagents skill runner cli" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Add Fixture-Based End-to-End Runtime Test

**Files:**
- Modify: `tests/test_skill_runtime_runner.py`

- [ ] **Step 1: Write the end-to-end test**

Append this test to `tests/test_skill_runtime_runner.py`:

```python
def test_skill_runtime_end_to_end_without_llm_calls(tmp_path):
    runtime = load_runtime()
    config = base_config(tmp_path, selected_analysts=["market"])
    state_path = runtime.init_run(write_config(tmp_path, config))
    report_dir = state_path.parent

    role_content = {
        "market_analyst": "market report",
        "bull_researcher": "bull report",
        "bear_researcher": "bear report",
        "research_manager": "**Recommendation**: Buy",
        "trader": "**Action**: Buy\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "risk_aggressive": "aggressive risk",
        "risk_conservative": "conservative risk",
        "risk_neutral": "neutral risk",
        "portfolio_manager": (
            "**Rating**: Buy\n"
            "**Executive Summary**: summary\n"
            "**Investment Thesis**: thesis"
        ),
    }

    while True:
        packet_path = runtime.next_step(report_dir)
        packet = read_json(packet_path)
        if packet["status"] == "complete":
            break
        Path(packet["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(packet["output_path"]).write_text(role_content[packet["role_id"]], encoding="utf-8")
        runtime.apply_step(report_dir, role_id=packet["role_id"])

    result = runtime.finalize_run(report_dir)
    state = read_json(state_path)

    assert result["rating"] == "Buy"
    assert state["skill_runtime"]["status"] == "completed"
    assert state["skill_runtime"]["completed_steps"] == [
        "market_analyst",
        "bull_researcher",
        "bear_researcher",
        "research_manager",
        "trader",
        "risk_aggressive",
        "risk_conservative",
        "risk_neutral",
        "portfolio_manager",
    ]
    assert (report_dir / "complete_report.md").exists()
```

- [ ] **Step 2: Run the end-to-end test to verify it passes**

Run:

```bash
pytest tests/test_skill_runtime_runner.py::test_skill_runtime_end_to_end_without_llm_calls -v
```

Expected: PASS.

- [ ] **Step 3: Commit Task 7**

Run:

```bash
git add tests/test_skill_runtime_runner.py
git commit -m "test: cover tradingagents skill runtime end to end" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Update Skill Documentation and Artifact Tests

**Files:**
- Modify: `skills/tradingagents/SKILL.md`
- Modify: `skills/tradingagents/README.md`
- Modify: `tests/test_skill_version_artifacts.py`

- [ ] **Step 1: Write failing artifact tests for runner files and docs**

Modify `tests/test_skill_version_artifacts.py` by adding the two new script paths to the existing `EXPECTED_SKILL_FILES` list:

```python
SKILL_DIR / "scripts" / "runtime.py",
SKILL_DIR / "scripts" / "skill_runner.py",
```

Then add this test near the existing README and skill text tests:

```python
def test_skill_docs_explain_deterministic_runner_usage():
    readme = (SKILL_DIR / "README.md").read_text(encoding="utf-8")
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, skill_text):
        assert "skill_runner.py init-run" in text
        assert "skill_runner.py next-step" in text
        assert "skill_runner.py apply-step" in text
        assert "skill_runner.py finalize-run" in text
        assert "tool_request.json" in text
        assert "state.json" in text
```

- [ ] **Step 2: Run the artifact test to verify it fails**

Run:

```bash
pytest tests/test_skill_version_artifacts.py::test_skill_docs_explain_deterministic_runner_usage -v
```

Expected: FAIL because the docs do not mention the new runner commands.

- [ ] **Step 3: Update `SKILL.md` runtime instructions**

In `skills/tradingagents/SKILL.md`, replace the current `## Workflow` and `## Role Execution Rules` sections with this text:

````markdown
## Deterministic Runtime Workflow

Use the deterministic runner scripts for skill runs. They preserve the original workflow order, state transitions, role counters, report paths, tool allowlists, final report assembly, and rating extraction while keeping the host coding agent as the model runtime.

Start a run:

```bash
python skills/tradingagents/scripts/skill_runner.py init-run path/to/config.json
```

The command prints the path to `state.json` under `results_dir/<TICKER>_<TRADE_DATE>/`.

For each role:

```bash
python skills/tradingagents/scripts/skill_runner.py next-step path/to/results/TICKER_YYYY-MM-DD
```

Read the generated `next_step.json`. It contains the role id, source prompt path, allowed tools, input state, required markers, `tool_request.json` path, and output path.

If an analyst needs live data, write `tool_request.json` using the role id, approved tool name, and JSON arguments, then run:

```bash
python skills/tradingagents/scripts/skill_runner.py run-tool-request path/to/results/TICKER_YYYY-MM-DD
```

Use the generated tool transcript as context for the same role. Do not call tools outside the runner.

After writing the role report to the packet's `output_path`, apply it:

```bash
python skills/tradingagents/scripts/skill_runner.py apply-step path/to/results/TICKER_YYYY-MM-DD --role-id ROLE_ID
```

Repeat `next-step` and `apply-step` until `next_step.json` reports completion. Then finalize:

```bash
python skills/tradingagents/scripts/skill_runner.py finalize-run path/to/results/TICKER_YYYY-MM-DD
```

Finalization writes `complete_report.md`, `TradingAgentsStrategy_logs/full_states_log_<TRADE_DATE>.json`, updates `state.json`, and returns the parsed final rating.

## Role Execution Rules

For each generated `next_step.json` packet:

1. Read the role entry from the packet.
2. Read the role's `source_path` file from the repository root.
3. Preserve the current prompt wording and role intent from that source file.
4. Use only the packet's `input_state`, approved tool transcripts, and allowed tools.
5. Write the role output exactly to the packet's `output_path`.
6. Run `apply-step` before moving to the next role.

Only the runner may advance `state.json`. Do not let a later role rewrite earlier reports. Later roles may quote or critique earlier outputs, matching the original multi-agent handoff.
````

- [ ] **Step 4: Update `README.md` runner usage**

In `skills/tradingagents/README.md`, replace the current "Prompt Claude Code" and "Assemble the final report" usage sections with this text:

````markdown
## Run with the deterministic skill runner

Initialize the run:

```bash
python skills/tradingagents/scripts/skill_runner.py init-run my-trading-run.json
```

The command prints:

```text
reports/skill_runs/NVDA_2026-05-04/state.json
```

Generate the next role packet:

```bash
python skills/tradingagents/scripts/skill_runner.py next-step reports/skill_runs/NVDA_2026-05-04
```

Read `next_step.json`, then use the host coding agent as the model runtime for that role. The agent should read the packet's `source_path`, use only the packet's `input_state`, write the role report to `output_path`, and preserve any required markers.

When an analyst needs live data, write `tool_request.json` in the run directory:

```json
{
  "role_id": "market_analyst",
  "tool": "get_stock_data",
  "arguments": {
    "symbol": "NVDA",
    "start_date": "2026-04-01",
    "end_date": "2026-05-04"
  }
}
```

Run the approved tool request through the deterministic gate:

```bash
python skills/tradingagents/scripts/skill_runner.py run-tool-request reports/skill_runs/NVDA_2026-05-04
```

After the role report exists, apply it:

```bash
python skills/tradingagents/scripts/skill_runner.py apply-step reports/skill_runs/NVDA_2026-05-04 --role-id market_analyst
```

Repeat `next-step`, role execution, and `apply-step` until `next_step.json` reports completion.

Finalize the run:

```bash
python skills/tradingagents/scripts/skill_runner.py finalize-run reports/skill_runs/NVDA_2026-05-04
```

Finalization creates `complete_report.md`, writes `TradingAgentsStrategy_logs/full_states_log_<TRADE_DATE>.json`, updates `state.json`, and returns the parsed final rating.
````

- [ ] **Step 5: Run the artifact tests**

Run:

```bash
pytest tests/test_skill_version_artifacts.py::test_skill_package_core_files_exist tests/test_skill_version_artifacts.py::test_skill_docs_explain_deterministic_runner_usage -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add skills/tradingagents/SKILL.md skills/tradingagents/README.md tests/test_skill_version_artifacts.py
git commit -m "docs: document deterministic tradingagents skill runner" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Full Verification

**Files:**
- Verify all files changed by Tasks 1 through 8.

- [ ] **Step 1: Run the focused skill tests**

Run:

```bash
pytest tests/test_skill_runtime_runner.py tests/test_skill_version_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
pytest
```

Expected: PASS.

- [ ] **Step 3: Inspect the final diff**

Run:

```bash
git --no-pager diff --stat HEAD
git --no-pager status --short
```

Expected: no unstaged changes after the previous task commits. If there are uncommitted changes from verification artifacts under temporary directories, remove only those generated by this plan.

- [ ] **Step 4: Record final verification in the handoff**

Use the exact pytest commands and observed outcomes from Steps 1 and 2 in the final handoff.

---

## Implementation Notes

- Keep `runtime.py` deterministic and free of LLM provider client construction.
- Keep prompt source text in the original `tradingagents/agents/` files.
- Treat `prompt_manifest.json` and `workflow.json` as maps; authoritative behavior remains in the existing Python source.
- Use `safe_ticker_component()` for any ticker or symbol value that can affect paths or tool calls.
- Let model nondeterminism remain in role report prose. The runner's job is to remove avoidable workflow drift.
