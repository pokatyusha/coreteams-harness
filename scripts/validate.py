"""Offline format/routing checks. No network, execution or permission grants."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
IDS = {a["agent_id"] for a in REGISTRY["agents"]} | {REGISTRY["coordinator"]["agent_id"]}
PERMISSIONS = {"read_repo", "run_local_tests", "edit_scoped_files", "publish_branch", "open_draft_pr", "post_issue_reply"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip()) and "<" not in value


def sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value)) and value != "0" * 40


def relative_path(value):
    return nonempty(value) and "\\" not in value and ":" not in value and not value.startswith("/") and ".." not in value.split("/") and not any(c in value for c in "*?[]")


def string_list(value):
    return isinstance(value, list) and bool(value) and all(nonempty(x) for x in value)


def validate_message(m):
    require(isinstance(m, dict), "message must be an object")
    require(m.get("protocol_version") == "1.0", "unsupported protocol")
    require(nonempty(m.get("request_id")), "missing request_id")
    require(m.get("from") in IDS and m.get("to") in IDS and m["from"] != m["to"], "unknown or identical sender/recipient")
    require(sha(m.get("harness_sha")), "harness_sha must be a full SHA")
    if m.get("kind") == "request":
        op = m.get("operation")
        require(op in {"connection_check", "contract_review", "code_change"}, "unsupported operation")
        p = m.get("permissions")
        require(isinstance(p, list) and all(isinstance(x, str) and x in PERMISSIONS for x in p), "unsupported permission; merge/deploy/background forbidden")
        require("read_repo" in p, "read_repo required")
        authority = m.get("authority", {})
        require(nonempty(authority.get("github_login")) and str(authority.get("evidence_url", "")).startswith("https://github.com/"), "human authority reference required; verify author separately")
        require(nonempty(m.get("goal")) and string_list(m.get("acceptance_checks")) and string_list(m.get("limits")), "goal, acceptance_checks and limits required")
        require(isinstance(m.get("contracts"), list), "contracts list required")
        if op == "connection_check":
            require(m.get("source") is None and set(p) <= {"read_repo", "post_issue_reply"} and not m["contracts"], "connection_check cannot touch product code/tests")
        else:
            s = m.get("source")
            require(isinstance(s, dict), "source required")
            require(s.get("repository") == REGISTRY["source_repository"] and sha(s.get("base_sha")), "source repository/full SHA mismatch")
            paths = s.get("allowed_paths")
            require(isinstance(paths, list) and bool(paths) and all(relative_path(x) for x in paths), "scope must use literal safe relative paths")
            if op == "code_change":
                require("edit_scoped_files" in p, "code_change requires explicit edit permission")
            else:
                require(not set(p) & {"edit_scoped_files", "publish_branch", "open_draft_pr"}, "contract_review cannot authorize source edits/publication")
        require("open_draft_pr" not in p or "publish_branch" in p, "draft PR requires publish_branch")
        for c in m["contracts"]:
            require(isinstance(c, dict) and c.get("repository") == REGISTRY["source_repository"] and relative_path(c.get("path")) and sha(c.get("sha")) and c.get("state") in {"proposed", "accepted", "unknown"}, "invalid contract reference")
    elif m.get("kind") == "event":
        require(nonempty(m.get("event_id")), "event_id required")
        require(m.get("status") in {"accepted", "blocked", "completed", "verified", "needs_changes"}, "unsupported status")
        require(m.get("source_sha") is None or sha(m.get("source_sha")), "invalid source_sha")
        dt = datetime.fromisoformat(m.get("recorded_at", "").replace("Z", "+00:00"))
        require(dt.tzinfo is not None, "recorded_at needs timezone")
        require(nonempty(m.get("summary")) and isinstance(m.get("blockers"), list), "summary/blockers required")
        if m["status"] == "blocked":
            require(string_list(m["blockers"]), "blocked needs a concrete blocker")
        if m["status"] == "completed":
            require(isinstance(m.get("artifacts"), list) and isinstance(m.get("checks"), list) and bool(m["checks"]), "completed needs artifacts/checks")
            require(string_list(m.get("limitations")) and nonempty(m.get("next_action")), "completed needs limitations/next_action")
            for c in m["checks"]:
                require(isinstance(c, dict) and nonempty(c.get("name")) and c.get("outcome") in {"PASS", "FAIL", "NOT_RUN"}, "invalid check")
                if c["outcome"] != "NOT_RUN":
                    require(nonempty(c.get("command")) or nonempty(c.get("evidence_url")), "PASS/FAIL needs command or evidence")
    else:
        raise ValueError("unsupported message kind")


def validate_pair(request, event):
    validate_message(request)
    validate_message(event)
    require(request["kind"] == "request" and event["kind"] == "event", "expected request and event")
    require(request["request_id"] == event["request_id"] and request["harness_sha"] == event["harness_sha"], "request/harness identity mismatch")
    expected = (request["from"], request["to"]) if event["status"] in {"verified", "needs_changes"} else (request["to"], request["from"])
    require((event["from"], event["to"]) == expected, "response addressed to wrong agent")
    source_sha = request["source"]["base_sha"] if request["source"] else None
    # Completed source_sha is the actually tested revision; accepted confirms the input.
    if event["status"] in {"accepted", "blocked"} or request["operation"] == "connection_check":
        require(event["source_sha"] == source_sha, "input source SHA changed")
    elif request["operation"] == "contract_review":
        require(event["source_sha"] == source_sha, "reviewed source SHA changed")
    elif event["status"] == "completed":
        require(sha(event["source_sha"]) and bool(event["artifacts"]), "code result needs tested SHA and artifact links")


def validate_binding(b):
    require(b.get("agent_id") in IDS, "unknown agent binding")
    require(nonempty(b.get("github_login")) and sha(b.get("harness_sha")), "login and harness SHA required")
    require(b.get("source_repository") == REGISTRY["source_repository"] and nonempty(b.get("source_branch")) and sha(b.get("source_sha")), "source binding incomplete")
    root = b.get("source_root", "")
    require(nonempty(root) and (PureWindowsPath(root).is_absolute() or PurePosixPath(root).is_absolute()), "absolute local source root required")
    require(string_list(b.get("allowed_paths")) and all(relative_path(x) for x in b["allowed_paths"]), "literal scope required")
    require(b.get("mode") == "manual-one-request", "binding must remain manual")


def validate_package():
    agent_ids = [a["agent_id"] for a in REGISTRY["agents"]]
    require(len(set(agent_ids)) == len(agent_ids) == 3 and "coordinator" not in agent_ids, "duplicate/missing roles")
    require(REGISTRY["background_checks"] is False and REGISTRY["merges_allowed"] is False and REGISTRY["mode"] == "manual-one-request", "manual/no-merge settings changed")
    for a in REGISTRY["agents"]:
        require((ROOT / a["profile"]).is_file(), "missing profile")
    require(not (ROOT / ".github/workflows").exists(), "background/CI workflows not part of this package")
    for file in ["README.md", "AGENTS.md", "CLAUDE.md", "docs/connect.md", "docs/exchange.md", "docs/architecture.md"]:
        require((ROOT / file).is_file(), f"missing {file}")
    for file in ["request.json", "ack.json", "result.json"]:
        validate_message(json.loads((ROOT / "templates" / file).read_text(encoding="utf-8")))
    request = json.loads((ROOT / "templates/request.json").read_text(encoding="utf-8"))
    for file in ["ack.json", "result.json"]:
        validate_pair(request, json.loads((ROOT / "templates" / file).read_text(encoding="utf-8")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", type=Path)
    parser.add_argument("--request", type=Path, help="Match --message event against this request")
    parser.add_argument("--binding", type=Path)
    args = parser.parse_args()
    try:
        validate_package()
        if args.message:
            m = json.loads(args.message.read_text(encoding="utf-8"))
            validate_message(m)
            if args.request:
                validate_pair(json.loads(args.request.read_text(encoding="utf-8")), m)
        require(not args.request or args.message, "--request requires --message event")
        if args.binding:
            validate_binding(json.loads(args.binding.read_text(encoding="utf-8")))
        print("PASS: offline package/message/binding checks; no live connection or authority verified.")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    main()
