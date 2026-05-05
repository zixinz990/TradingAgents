"""Validate JSON config files for TradingAgents skill runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS
from tradingagents.dataflows.utils import safe_ticker_component


SUPPORTED_ANALYSTS = {"market", "social", "news", "fundamentals"}
SUPPORTED_VENDORS = set(VENDOR_LIST)
SUPPORTED_TOOL_VENDOR_METHODS = set(VENDOR_METHODS)
VENDOR_CATEGORIES = {
    "core_stock_apis",
    "technical_indicators",
    "fundamental_data",
    "news_data",
}
ALLOWED_FIELDS = {
    "ticker",
    "trade_date",
    "selected_analysts",
    "max_debate_rounds",
    "max_risk_discuss_rounds",
    "output_language",
    "results_dir",
    "data_vendors",
    "tool_vendors",
    "data_inputs",
}


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("config root must be a JSON object")
    return loaded


def is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
    )


def validate_vendor_string(
    errors: list[str],
    field_name: str,
    value: Any,
    supported_vendors: set[str] | None = None,
) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a vendor string")
        return
    allowed_vendors = SUPPORTED_VENDORS if supported_vendors is None else supported_vendors
    vendors = [vendor.strip() for vendor in value.split(",")]
    if any(not vendor for vendor in vendors):
        errors.append(f"{field_name} must not contain empty vendor entries")
        return
    unsupported_vendors = sorted(set(vendors) - allowed_vendors)
    if unsupported_vendors:
        errors.append(
            f"{field_name} contains unsupported vendors: "
            + ", ".join(unsupported_vendors)
        )


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    unsupported_fields = sorted(set(config) - ALLOWED_FIELDS)
    if unsupported_fields:
        errors.append(
            "config contains unsupported fields: "
            + ", ".join(unsupported_fields)
        )

    ticker = config.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        errors.append("ticker is required")
    else:
        try:
            safe_ticker_component(ticker)
        except ValueError:
            errors.append("ticker must be a safe ticker path component")

    trade_date = config.get("trade_date")
    if not isinstance(trade_date, str):
        errors.append("trade_date must use YYYY-MM-DD format")
    else:
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            errors.append("trade_date must use YYYY-MM-DD format")

    analysts = config.get("selected_analysts")
    if not isinstance(analysts, list) or not all(isinstance(item, str) for item in analysts):
        errors.append("selected_analysts must be a list of analyst names")
    elif not analysts:
        errors.append("selected_analysts must contain at least one analyst")
    else:
        unsupported = sorted(set(analysts) - SUPPORTED_ANALYSTS)
        if unsupported:
            errors.append(
                "selected_analysts contains unsupported analysts: "
                + ", ".join(unsupported)
            )
        if len(analysts) != len(set(analysts)):
            errors.append("selected_analysts must not contain duplicates")

    for key in ("max_debate_rounds", "max_risk_discuss_rounds"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"{key} must be a positive integer")

    results_dir = config.get("results_dir")
    if not isinstance(results_dir, str) or not results_dir.strip():
        errors.append("results_dir is required")
    elif not is_safe_relative_path(results_dir):
        errors.append("results_dir must be a safe relative path")

    output_language = config.get("output_language", "English")
    if not isinstance(output_language, str):
        errors.append("output_language must be a string")

    data_vendors = config.get("data_vendors", {})
    if data_vendors is not None:
        if not isinstance(data_vendors, dict):
            errors.append("data_vendors must be an object")
        else:
            unsupported_categories = sorted(set(data_vendors) - VENDOR_CATEGORIES)
            if unsupported_categories:
                errors.append(
                    "data_vendors contains unsupported categories: "
                    + ", ".join(unsupported_categories)
                )
            for category, vendor_value in data_vendors.items():
                validate_vendor_string(errors, f"data_vendors.{category}", vendor_value)

    tool_vendors = config.get("tool_vendors", {})
    if tool_vendors is not None:
        if not isinstance(tool_vendors, dict):
            errors.append("tool_vendors must be an object")
        else:
            unsupported_tools = sorted(set(tool_vendors) - SUPPORTED_TOOL_VENDOR_METHODS)
            if unsupported_tools:
                errors.append(
                    "tool_vendors contains unsupported tools: "
                    + ", ".join(unsupported_tools)
                )
            for tool_name, vendor_value in tool_vendors.items():
                supported_vendors = (
                    set(VENDOR_METHODS[tool_name])
                    if tool_name in VENDOR_METHODS
                    else SUPPORTED_VENDORS
                )
                validate_vendor_string(
                    errors,
                    f"tool_vendors.{tool_name}",
                    vendor_value,
                    supported_vendors,
                )

    data_inputs = config.get("data_inputs", {})
    if data_inputs is not None:
        if not isinstance(data_inputs, dict):
            errors.append("data_inputs must be an object")
        else:
            invalid_inputs = sorted(
                key for key, value in data_inputs.items()
                if not isinstance(value, str)
            )
            if invalid_inputs:
                errors.append(
                    "data_inputs values must be strings: "
                    + ", ".join(invalid_inputs)
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Path to a TradingAgents skill config JSON file")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid config: {exc}")
        return 1

    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1

    print("Config valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
