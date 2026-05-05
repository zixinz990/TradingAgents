"""Assemble TradingAgents skill role reports into complete_report.md."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ANALYST_SECTIONS = {
    "market": ("Market Analyst", "1_analysts/market.md"),
    "social": ("Social Media Analyst", "1_analysts/sentiment.md"),
    "news": ("News Analyst", "1_analysts/news.md"),
    "fundamentals": ("Fundamentals Analyst", "1_analysts/fundamentals.md"),
}

DEFAULT_ANALYST_ORDER = ["market", "social", "news", "fundamentals"]

DOWNSTREAM_SECTIONS = [
    ("Bull Researcher", "2_research/bull.md"),
    ("Bear Researcher", "2_research/bear.md"),
    ("Research Manager", "2_research/manager.md"),
    ("Trader", "3_trading/trader.md"),
    ("Aggressive Risk Analyst", "4_risk/aggressive.md"),
    ("Conservative Risk Analyst", "4_risk/conservative.md"),
    ("Neutral Risk Analyst", "4_risk/neutral.md"),
    ("Portfolio Manager", "5_portfolio/decision.md"),
]

TRADER_FINAL_PROPOSAL_MARKER = "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**"
TRADER_FINAL_PROPOSAL_RE = re.compile(
    r"^FINAL TRANSACTION PROPOSAL: \*\*(BUY|HOLD|SELL)\*\*$",
    re.MULTILINE,
)
REQUIRED_FRAGMENT_MARKERS = {
    "2_research/manager.md": ("**Recommendation**:",),
    "3_trading/trader.md": ("**Action**:",),
    "5_portfolio/decision.md": (
        "**Rating**:",
        "**Executive Summary**:",
        "**Investment Thesis**:",
    ),
}


def section_order(selected_analysts: list[str] | None = None) -> list[tuple[str, str]]:
    analysts = selected_analysts or DEFAULT_ANALYST_ORDER
    unsupported = sorted(set(analysts) - set(ANALYST_SECTIONS))
    if unsupported:
        raise ValueError(
            "unsupported selected analysts for report assembly: "
            + ", ".join(unsupported)
        )
    return [ANALYST_SECTIONS[analyst] for analyst in analysts] + DOWNSTREAM_SECTIONS


def assert_report_dir_inside_results_dir(report_dir: Path, results_dir: Path | str | None) -> None:
    if results_dir is None:
        return
    base = Path(results_dir).resolve()
    target = report_dir.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("report_dir must be inside results_dir") from exc


def assert_required_markers(relative_path: str, content: str) -> None:
    for marker in REQUIRED_FRAGMENT_MARKERS.get(relative_path, ()):
        if marker not in content:
            raise ValueError(f"{relative_path} missing required marker {marker}")
    if (
        relative_path == "3_trading/trader.md"
        and not TRADER_FINAL_PROPOSAL_RE.search(content)
    ):
        raise ValueError(
            f"{relative_path} missing required marker {TRADER_FINAL_PROPOSAL_MARKER}"
        )


def assemble_report(
    report_dir: Path | str,
    selected_analysts: list[str] | None = None,
    results_dir: Path | str | None = None,
) -> Path:
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        raise FileNotFoundError(f"report directory does not exist: {report_dir}")
    assert_report_dir_inside_results_dir(report_dir, results_dir)

    sections = section_order(selected_analysts)
    missing = [
        relative_path
        for _, relative_path in sections
        if not (report_dir / relative_path).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "missing required report fragments: " + ", ".join(missing)
        )

    parts = ["# TradingAgents Complete Report", ""]
    for heading, relative_path in sections:
        section_path = report_dir / relative_path
        content = section_path.read_text(encoding="utf-8").strip()
        assert_required_markers(relative_path, content)
        parts.extend([f"## {heading}", ""])
        parts.extend([content, ""])

    output_path = report_dir / "complete_report.md"
    output_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output_path


def load_assembly_config(config_path: Path | None) -> tuple[list[str] | None, str | None]:
    if config_path is None:
        return None, None
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    return config.get("selected_analysts"), config.get("results_dir")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path, help="Directory containing role report fragments")
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional skill config JSON for selected analyst and results_dir checks",
    )
    args = parser.parse_args(argv)

    selected_analysts, results_dir = load_assembly_config(args.config)
    output_path = assemble_report(
        args.report_dir,
        selected_analysts=selected_analysts,
        results_dir=results_dir,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
