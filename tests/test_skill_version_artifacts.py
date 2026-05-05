import importlib.util
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "tradingagents"

pytestmark = pytest.mark.unit

EXPECTED_SKILL_FILES = [
    SKILL_DIR / "README.md",
    SKILL_DIR / "SKILL.md",
    SKILL_DIR / "config.schema.json",
    SKILL_DIR / "config.example.json",
    SKILL_DIR / "prompt_manifest.json",
    SKILL_DIR / "workflow.json",
    SKILL_DIR / "scripts" / "validate_config.py",
    SKILL_DIR / "scripts" / "assemble_report.py",
    SKILL_DIR / "scripts" / "runtime.py",
    SKILL_DIR / "scripts" / "skill_runner.py",
]

EXPECTED_ROLE_IDS = {
    "market_analyst",
    "social_media_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "bull_researcher",
    "bear_researcher",
    "research_manager",
    "trader",
    "risk_aggressive",
    "risk_conservative",
    "risk_neutral",
    "portfolio_manager",
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_package_core_files_exist():
    missing = [path for path in EXPECTED_SKILL_FILES if not path.exists()]
    assert missing == []


def test_skill_readme_explains_claude_code_usage():
    readme = (SKILL_DIR / "README.md").read_text(encoding="utf-8")

    assert "Claude Code" in readme
    assert ".claude/skills/tradingagents" in readme
    assert "config.example.json" in readme
    assert "validate_config.py" in readme
    assert "assemble_report.py" in readme
    assert "Do not instantiate" in readme
    assert "tradingagents/agents/" in readme
    assert "tradingagents/graph/" in readme
    assert "pip install -e ." in readme
    assert "importable" in readme


def test_skill_declares_existing_prompts_and_workflow_as_source_of_truth():
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "source of truth" in skill_text.lower()
    assert "do not modify" in skill_text.lower()
    assert "tradingagents/agents/analysts/market_analyst.py" in skill_text
    assert "tradingagents/agents/managers/portfolio_manager.py" in skill_text
    assert "tradingagents/graph/setup.py" in skill_text
    assert "tradingagents/graph/conditional_logic.py" in skill_text
    assert "pip install -e ." in skill_text
    assert "importable" in skill_text


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


def test_skill_docs_explain_agent_driven_automated_run():
    readme = (SKILL_DIR / "README.md").read_text(encoding="utf-8")
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, skill_text):
        assert "Automated Agent Run" in text
        assert "run to completion" in text
        assert "Do not stop after" in text
        assert "finalize-run" in text

    assert "Use the tradingagents skill with this config and run it to completion" in readme
    assert "When the user asks to automate" in skill_text


def test_prompt_manifest_covers_all_current_agent_roles_without_copying_prompts():
    manifest = json.loads((SKILL_DIR / "prompt_manifest.json").read_text(encoding="utf-8"))
    roles = {role["id"]: role for role in manifest["roles"]}

    assert set(roles) == EXPECTED_ROLE_IDS
    assert manifest["source_of_truth_policy"] == "existing_code"

    for role in roles.values():
        assert (ROOT / role["source_path"]).exists()
        assert role["output_key"]
        assert role["report_path"]
        assert "prompt_text" not in role


def test_prompt_manifest_matches_authoritative_news_tools():
    manifest = json.loads((SKILL_DIR / "prompt_manifest.json").read_text(encoding="utf-8"))
    roles = {role["id"]: role for role in manifest["roles"]}

    assert roles["news_analyst"]["allowed_tools"] == ["get_news", "get_global_news"]


def test_workflow_manifest_preserves_current_multi_agent_order():
    workflow = json.loads((SKILL_DIR / "workflow.json").read_text(encoding="utf-8"))

    assert workflow["source_of_truth"]["graph_setup"] == "tradingagents/graph/setup.py"
    assert workflow["source_of_truth"]["conditional_logic"] == "tradingagents/graph/conditional_logic.py"
    assert [stage["id"] for stage in workflow["stages"]] == [
        "analysts",
        "investment_debate",
        "research_manager",
        "trader",
        "risk_debate",
        "portfolio_manager",
    ]
    assert workflow["stages"][0]["default_order"] == [
        "market_analyst",
        "social_media_analyst",
        "news_analyst",
        "fundamentals_analyst",
    ]
    assert workflow["stages"][1]["cycle"] == ["bull_researcher", "bear_researcher"]
    assert workflow["stages"][4]["cycle"] == [
        "risk_aggressive",
        "risk_conservative",
        "risk_neutral",
    ]


def test_config_schema_rejects_duplicate_analysts_and_unsafe_tickers():
    schema = json.loads((SKILL_DIR / "config.schema.json").read_text(encoding="utf-8"))

    assert schema["properties"]["selected_analysts"]["uniqueItems"] is True
    assert schema["properties"]["max_debate_rounds"]["minimum"] == 1
    assert schema["properties"]["max_risk_discuss_rounds"]["minimum"] == 1
    ticker_pattern = schema["properties"]["ticker"]["pattern"]
    assert re.fullmatch(ticker_pattern, "^GSPC")
    assert re.fullmatch(ticker_pattern, "BRK.B")
    assert re.fullmatch(ticker_pattern, ".") is None
    assert re.fullmatch(ticker_pattern, "..") is None
    assert re.fullmatch(ticker_pattern, "...") is None
    assert re.fullmatch(ticker_pattern, "../evil") is None
    assert schema["properties"]["ticker"]["maxLength"] == 32
    assert "relative" in schema["properties"]["results_dir"]["description"].lower()


def test_config_schema_restricts_tool_vendor_overrides_to_known_tools_and_vendors():
    schema = json.loads((SKILL_DIR / "config.schema.json").read_text(encoding="utf-8"))
    from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS

    tool_vendor_schema = schema["properties"]["tool_vendors"]
    vendor_pattern = tool_vendor_schema["additionalProperties"]["pattern"]
    vendor_alternatives = "|".join(re.escape(vendor) for vendor in VENDOR_LIST)

    assert set(tool_vendor_schema["propertyNames"]["enum"]) == set(VENDOR_METHODS)
    assert vendor_pattern == rf"^(?:{vendor_alternatives})(?:\s*,\s*(?:{vendor_alternatives}))*$"
    assert all(re.fullmatch(vendor_pattern, vendor) for vendor in VENDOR_LIST)
    assert re.fullmatch(vendor_pattern, ",".join(VENDOR_LIST))
    assert re.fullmatch(vendor_pattern, "not_a_vendor") is None


def test_validate_config_accepts_example_and_rejects_invalid_values(tmp_path):
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config",
    )
    valid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))

    assert validator.validate_config(valid_config) == []

    invalid_config = dict(valid_config)
    invalid_config.pop("ticker")
    invalid_config["trade_date"] = "05/04/2026"
    invalid_config["selected_analysts"] = ["market", "macro"]
    invalid_config["max_debate_rounds"] = -1
    invalid_config["max_risk_discuss_rounds"] = "one"

    errors = validator.validate_config(invalid_config)

    assert "ticker is required" in errors
    assert "trade_date must use YYYY-MM-DD format" in errors
    assert "selected_analysts contains unsupported analysts: macro" in errors
    assert "max_debate_rounds must be a positive integer" in errors
    assert "max_risk_discuss_rounds must be a positive integer" in errors


def test_validate_config_rejects_zero_round_counts():
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_positive_rounds",
    )
    invalid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))
    invalid_config["max_debate_rounds"] = 0
    invalid_config["max_risk_discuss_rounds"] = 0

    errors = validator.validate_config(invalid_config)

    assert "max_debate_rounds must be a positive integer" in errors
    assert "max_risk_discuss_rounds must be a positive integer" in errors


def test_validate_config_rejects_schema_drift_and_unsafe_paths():
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_strict",
    )
    valid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))
    invalid_config = dict(valid_config)
    invalid_config["unexpected"] = True
    invalid_config["selected_analysts"] = ["market", "market"]
    invalid_config["results_dir"] = "../outside"
    invalid_config["output_language"] = 123
    invalid_config["tool_vendors"] = {"get_news": 123}
    invalid_config["data_inputs"] = {"market": 123}

    errors = validator.validate_config(invalid_config)

    assert "config contains unsupported fields: unexpected" in errors
    assert "selected_analysts must not contain duplicates" in errors
    assert "results_dir must be a safe relative path" in errors
    assert "output_language must be a string" in errors
    assert "tool_vendors.get_news must be a vendor string" in errors
    assert "data_inputs values must be strings: market" in errors


def test_validate_config_supported_vendors_match_canonical_vendor_list():
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_vendors",
    )
    from tradingagents.dataflows.interface import VENDOR_LIST

    assert validator.SUPPORTED_VENDORS == set(VENDOR_LIST)


def test_validate_config_rejects_unsupported_tool_vendor_overrides():
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_tool_vendors",
    )
    valid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))

    valid_config["tool_vendors"] = {"get_news": "yfinance"}
    assert validator.validate_config(valid_config) == []

    invalid_config = dict(valid_config)
    invalid_config["tool_vendors"] = {
        "get_news": "not_a_vendor",
        "get_stock_data": "",
        "not_a_tool": "yfinance",
    }

    errors = validator.validate_config(invalid_config)

    assert "tool_vendors contains unsupported tools: not_a_tool" in errors
    assert "tool_vendors.get_news contains unsupported vendors: not_a_vendor" in errors
    assert "tool_vendors.get_stock_data must be a vendor string" in errors


def test_validate_config_rejects_method_specific_unsupported_tool_vendors(monkeypatch):
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_method_vendors",
    )
    valid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))
    monkeypatch.setitem(validator.VENDOR_METHODS, "get_news", {"yfinance": object()})

    valid_config["tool_vendors"] = {"get_news": "alpha_vantage"}
    errors = validator.validate_config(valid_config)

    assert "tool_vendors.get_news contains unsupported vendors: alpha_vantage" in errors


def test_validate_config_rejects_empty_vendor_entries():
    validator = load_module(
        SKILL_DIR / "scripts" / "validate_config.py",
        "skill_validate_config_empty_vendor_entries",
    )
    valid_config = json.loads((SKILL_DIR / "config.example.json").read_text(encoding="utf-8"))
    invalid_config = dict(valid_config)
    invalid_config["tool_vendors"] = {
        "get_news": "yfinance,",
        "get_stock_data": ",yfinance",
        "get_indicators": "yfinance,,alpha_vantage",
    }

    errors = validator.validate_config(invalid_config)

    assert errors.count("tool_vendors.get_news must not contain empty vendor entries") == 1
    assert errors.count("tool_vendors.get_stock_data must not contain empty vendor entries") == 1
    assert errors.count("tool_vendors.get_indicators must not contain empty vendor entries") == 1


def write_report_fragments(report_dir: Path, fragments: dict[str, str]) -> None:
    for relative_path, content in fragments.items():
        fragment_path = report_dir / relative_path
        fragment_path.parent.mkdir(parents=True, exist_ok=True)
        fragment_path.write_text(content, encoding="utf-8")


def complete_report_fragments() -> dict[str, str]:
    return {
        "1_analysts/market.md": "market report",
        "1_analysts/sentiment.md": "sentiment report",
        "1_analysts/news.md": "news report",
        "1_analysts/fundamentals.md": "fundamentals report",
        "2_research/bull.md": "bull report",
        "2_research/bear.md": "bear report",
        "2_research/manager.md": "**Recommendation**: Buy",
        "3_trading/trader.md": (
            "**Action**: Buy\n"
            "FINAL TRANSACTION PROPOSAL: **BUY**"
        ),
        "4_risk/aggressive.md": "aggressive risk",
        "4_risk/conservative.md": "conservative risk",
        "4_risk/neutral.md": "neutral risk",
        "5_portfolio/decision.md": (
            "**Rating**: Buy\n"
            "**Executive Summary**: Summary\n"
            "**Investment Thesis**: Thesis"
        ),
    }


def test_assemble_report_uses_stable_section_order(tmp_path):
    assembler = load_module(
        SKILL_DIR / "scripts" / "assemble_report.py",
        "skill_assemble_report",
    )
    report_dir = tmp_path / "NVDA_2026-05-04"

    write_report_fragments(report_dir, complete_report_fragments())

    output_path = assembler.assemble_report(report_dir)
    content = output_path.read_text(encoding="utf-8")

    assert output_path == report_dir / "complete_report.md"
    assert content.index("## Market Analyst") < content.index("## Social Media Analyst")
    assert content.index("## Trader") < content.index("## Portfolio Manager")
    assert "FINAL TRANSACTION PROPOSAL: **BUY**" in content
    assert "**Rating**: Buy" in content


def test_assemble_report_fails_when_required_fragment_is_missing(tmp_path):
    assembler = load_module(
        SKILL_DIR / "scripts" / "assemble_report.py",
        "skill_assemble_report_missing",
    )
    report_dir = tmp_path / "NVDA_2026-05-04"
    fragments = complete_report_fragments()
    fragments.pop("5_portfolio/decision.md")
    write_report_fragments(report_dir, fragments)

    with pytest.raises(FileNotFoundError, match="5_portfolio/decision.md"):
        assembler.assemble_report(report_dir)

    assert not (report_dir / "complete_report.md").exists()


@pytest.mark.parametrize(
    ("relative_path", "content", "missing_marker"),
    [
        ("2_research/manager.md", "manager report", "**Recommendation**:"),
        (
            "3_trading/trader.md",
            "FINAL TRANSACTION PROPOSAL: **BUY**",
            "**Action**:",
        ),
        (
            "3_trading/trader.md",
            "**Action**: Buy",
            "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**",
        ),
        ("5_portfolio/decision.md", "portfolio decision", "**Rating**:"),
        (
            "5_portfolio/decision.md",
            "**Rating**: Buy\n**Investment Thesis**: Thesis",
            "**Executive Summary**:",
        ),
        (
            "5_portfolio/decision.md",
            "**Rating**: Buy\n**Executive Summary**: Summary",
            "**Investment Thesis**:",
        ),
    ],
)
def test_assemble_report_fails_when_required_marker_is_missing(
    tmp_path,
    relative_path,
    content,
    missing_marker,
):
    assembler = load_module(
        SKILL_DIR / "scripts" / "assemble_report.py",
        "skill_assemble_report_missing_marker",
    )
    report_dir = tmp_path / "NVDA_2026-05-04"
    fragments = complete_report_fragments()
    fragments[relative_path] = content
    write_report_fragments(report_dir, fragments)

    with pytest.raises(
        ValueError,
        match=re.escape(f"{relative_path} missing required marker {missing_marker}"),
    ):
        assembler.assemble_report(report_dir)

    assert not (report_dir / "complete_report.md").exists()


def test_assemble_report_respects_selected_analyst_subset(tmp_path):
    assembler = load_module(
        SKILL_DIR / "scripts" / "assemble_report.py",
        "skill_assemble_report_subset",
    )
    report_dir = tmp_path / "NVDA_2026-05-04"
    fragments = complete_report_fragments()
    fragments.pop("1_analysts/sentiment.md")
    fragments.pop("1_analysts/news.md")
    fragments.pop("1_analysts/fundamentals.md")
    write_report_fragments(report_dir, fragments)

    output_path = assembler.assemble_report(report_dir, selected_analysts=["market"])
    content = output_path.read_text(encoding="utf-8")

    assert "## Market Analyst" in content
    assert "## Social Media Analyst" not in content
    assert "## Portfolio Manager" in content
