# (C) 2026 GoodData Corporation

"""Record and join workflow 3's deployment results across isolated runners."""

import argparse
import json
import os
import re
from pathlib import Path

PHASES = ("upload", "track", "comparison")
OUTCOMES = {"success", "failure", "cancelled", "not_attempted"}
RESULT = Path("deployment-result.json")
COLLECTION = Path("deployment-collection.json")


def scope() -> list[str]:
    """Read a nonempty, unique scope safe for artifact names and CLI output."""
    products = json.loads(os.environ["DATA_PRODUCTS"])
    if (
        not isinstance(products, list)
        or not products
        or any(
            not isinstance(dp, str) or not re.fullmatch(r"[\w.-]+", dp, re.ASCII)
            for dp in products
        )
        or len(products) != len(set(products))
    ):
        raise ValueError("Expected a nonempty JSON array of unique data product IDs")
    return products


def identity() -> dict[str, str]:
    """Bind a result to the immutable content and current workflow attempt."""
    return {
        "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "commit": os.environ["DEPLOY_COMMIT"],
        "version": os.environ["VERSION"],
    }


def record() -> int:
    outcomes = {}
    for phase in PHASES:
        value = os.environ.get(f"{phase.upper()}_OUTCOME", "")
        outcomes[phase] = value if value in OUTCOMES else "not_attempted"
    if outcomes["upload"] != "success":
        outcomes["comparison"] = "skipped"
    elif os.environ["VERSION_COMPARISON_ENABLED"] != "true":
        outcomes["comparison"] = "disabled"
    RESULT.write_text(
        json.dumps(
            {**identity(), "data_product_id": os.environ["DATA_PRODUCT_ID"], **outcomes}
        )
        + "\n"
    )
    return 0


def valid_record(data: object, expected: dict[str, str], comparison: bool) -> bool:
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        return False
    if any(not isinstance(data.get(phase), str) for phase in PHASES):
        return False
    if data.get("upload") not in OUTCOMES or data.get("track") not in OUTCOMES:
        return False
    if data["upload"] != "success":
        return data["track"] == "not_attempted" and data.get("comparison") == "skipped"
    allowed = OUTCOMES if comparison else {"disabled"}
    return data.get("comparison") in allowed


def collect() -> int:
    products = scope()
    expected = identity()
    comparison = os.environ["VERSION_COMPARISON_ENABLED"] == "true"
    records = {}
    seen = set()
    invalid = set()
    errors = []
    if not all(expected.values()):
        errors.append("Release identity is incomplete; preparation did not finish")
    for path in sorted(Path("deployment-results").rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except OSError, ValueError:
            errors.append(f"Unreadable result: {path.name}")
            continue
        dp = data.get("data_product_id") if isinstance(data, dict) else None
        if not isinstance(dp, str) or dp not in products:
            errors.append("Result has an unexpected data product")
            continue
        if dp in seen:
            invalid.add(dp)
            errors.append(f"Duplicate result for {dp}")
        seen.add(dp)
        if not valid_record(data, expected, comparison):
            invalid.add(dp)
            errors.append(f"Invalid result or release identity mismatch for {dp}")
        records[dp] = data
    for dp in invalid:
        records.pop(dp, None)
    for dp in products:
        if dp not in records:
            errors.append(f"Missing trustworthy result for {dp}; re-run all jobs")
    successful = [
        dp for dp in products if records.get(dp, {}).get("upload") == "success"
    ]
    COLLECTION.write_text(
        json.dumps({"records": records, "errors": errors, "successful_dps": successful})
        + "\n"
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"successful_dps={' '.join(successful)}\n")
    for error in errors:
        print(f"::error::{error}")
    return int(bool(errors))


def summary() -> int:
    from gdcloud.utils.markdown import md_code, md_table

    scope_errors = []
    try:
        products = scope()
    except ValueError, KeyError:
        products = []
        scope_errors.append("Release scope is unavailable or invalid")
    try:
        data = json.loads(COLLECTION.read_text())
    except OSError, ValueError:
        data = {
            "records": {},
            "errors": ["Result collection did not produce a readable result"],
            "successful_dps": [],
        }
    dependencies = json.loads(os.environ["DEPENDENCIES"])
    errors = [*scope_errors, *data["errors"]]
    for job, value in dependencies.items():
        result = value["result"]
        if result != "success" and not (
            job == "cleanup-feature-workspace" and result == "skipped"
        ):
            errors.append(f"{job}: {result}")
    if os.environ["COLLECTION_OUTCOME"] != "success":
        errors.append("Result collection failed")
    if os.environ["METADATA_EXPORT_ENABLED"] != "true":
        export = "disabled"
    elif not data["successful_dps"]:
        export = "skipped"
    else:
        export = os.environ["EXPORT_OUTCOME"]
        if export != "success":
            errors.append(f"Metadata export dispatch: {export}")
    rows = []
    for dp in products:
        record = data["records"].get(dp, {})
        statuses = [record.get(phase, "missing") for phase in PHASES]
        if statuses[0:2] != ["success", "success"] or statuses[2] not in {
            "success",
            "disabled",
        }:
            errors.append(f"Deployment incomplete for {dp}")
        rows.append([dp, *statuses])
    heading = "⚠️" if errors else "✅"
    lines = [
        f"## {heading} Deploy — Dev",
        "",
        f"Version: {md_code(os.environ.get('VERSION') or 'not prepared')}",
        "",
        *md_table(["Data Product", "Upload", "Tracking", "Version comparison"], rows),
        "",
        f"Metadata export dispatch: {export}",
        "",
        "Feature workspace cleanup job: "
        + dependencies["cleanup-feature-workspace"]["result"],
    ]
    if errors:
        lines += ["", *[f"- {error}" for error in errors]]
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
        output.write("\n".join(lines) + "\n")
    for error in errors:
        print(f"::error::{error}")
    return int(bool(errors))


def plan() -> int:
    from gdcloud.utils.markdown import md_table

    rows = [
        ["Environment", "dev"],
        ["Version", os.environ["VERSION"]],
        ["Previous version", os.environ["PREVIOUS_VERSION"]],
        ["Target branch", os.environ["DEFAULT_BRANCH"]],
        ["Data products", ", ".join(scope())],
    ]
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
        output.write(
            "## 📋 Deployment Plan\n\n" + "\n".join(md_table(["", ""], rows)) + "\n"
        )
    return 0


def validate_targets() -> int:
    from gdcloud.utils.config import get_config_value, get_workspace_id

    # Match get_workspace_config: gd-upload resolves host at environment scope.
    host = get_config_value("host", environment="dev")
    if not host:
        raise ValueError("Missing dev host")
    owners = {}
    for dp in scope():
        workspaces = get_workspace_id(
            "dev",
            dp,
            branch=os.environ["DEFAULT_BRANCH"],
            include_clone=True,
            quiet=True,
        )
        for workspace in workspaces:
            key = (host.rstrip("/"), workspace)
            if key in owners:
                raise ValueError(
                    f"Shared deployment destination for {owners[key]} and {dp}"
                )
            owners[key] = dp
    return 0


def main() -> int:
    commands = {
        "record": record,
        "collect": collect,
        "summary": summary,
        "plan": plan,
        "validate-targets": validate_targets,
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=commands)
    args = parser.parse_args()
    try:
        return commands[args.command]()
    except (OSError, ValueError, KeyError) as error:
        print(f"::error::{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
