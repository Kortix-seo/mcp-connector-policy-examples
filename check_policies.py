#!/usr/bin/env python3
"""Offline policy checker for a Kortix `kortix.yaml`.

Kortix decides a connector call in four levels, and the first match wins:

  1. project-wide `policies:` in kortix.yaml   (fully qualified, e.g. gmail.send_email)
  2. the calling agent's policy set            (agents.<name>.policy_sets, on that connector)
  3. the connector's own `policies:`           (relative, e.g. send_*, the base rules)
  4. no rule matched                           (sensitive holds the call, else policy.default_mode)

Source: https://kortix.com/docs/developers#connector-rules-and-approvals

This script reads lines and tracks indentation. It is not a YAML parser and it
does not load the document as data. It checks the policy fields described in
the README, and nothing else. It makes no network calls, needs no Kortix
project, and does not validate the file against a live project.

Exit codes: 0 every checked rule is well formed, 1 faults found, 2 file unreadable.
"""

import sys

# Allow = always_run, Ask = require_approval, Block = block.
ACTIONS = ("always_run", "require_approval", "block")
GLOB_CHARS = "*?[]"
# A lint cap of this script's own: the docs set no limit on conditions, and say
# every condition a rule carries must hold.
MAX_CONDITIONS = 10

LEVELS = (
    "1. project-wide policies: in kortix.yaml   fully qualified, e.g. gmail.send_email",
    "2. the calling agent's policy set          agents.<name>.policy_sets, on that connector",
    "3. the connector's own policies:           relative, e.g. send_*, the base rules",
    "4. no rule matched                         sensitive holds the call, else policy.default_mode",
)
SOURCE = "https://kortix.com/docs/developers#connector-rules-and-approvals"


def strip_comment(line):
    """Drop a trailing # comment, respecting simple quotes."""
    out = []
    quote = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def tokenize(text):
    """Return (indent, content, line number) for every non-blank, non-comment line."""
    tokens = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw.replace("\t", "  "))
        content = line.strip()
        if not content:
            continue
        indent = len(line) - len(line.lstrip(" "))
        tokens.append((indent, content, number))
    return tokens


def split_key(content):
    if ":" not in content:
        return None, None
    key, _, value = content.partition(":")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return (key or None), value


def parse_rules(tokens, i, stop_indent):
    """Parse a `- match:` list from tokens[i], stopping at indent <= stop_indent."""
    rules = []
    if i >= len(tokens):
        return rules, i
    item_indent = tokens[i][0]
    while i < len(tokens):
        indent, content, number = tokens[i]
        if indent <= stop_indent or indent != item_indent:
            break
        if not content.startswith("- "):
            break
        rule = {"line": number, "match": None, "action": None, "conditions": []}
        body = content[2:].strip()
        i += 1
        if body:
            key, value = split_key(body)
            if key in ("match", "action"):
                rule[key] = value
        condition = None
        condition_indent = None
        while i < len(tokens):
            indent, content, number = tokens[i]
            if indent <= stop_indent or indent <= item_indent:
                break
            if content.startswith("- "):
                condition = {"line": number, "arg": None, "match": None, "negate": None}
                condition_indent = indent
                body = content[2:].strip()
                if body:
                    key, value = split_key(body)
                    if key:
                        condition[key] = value
                rule["conditions"].append(condition)
                i += 1
                continue
            key, value = split_key(content)
            if condition is not None and indent > condition_indent:
                if key in ("arg", "match", "negate"):
                    condition[key] = value
            elif key == "conditions":
                pass
            elif key in ("match", "action"):
                rule[key] = value
            i += 1
        rules.append(rule)
    return rules, i


def find_section(tokens, name):
    for i, (indent, content, _) in enumerate(tokens):
        if indent == 0 and content == name + ":":
            return i
    return None


def parse_project_rules(tokens):
    start = find_section(tokens, "policies")
    if start is None:
        return []
    i = start + 1
    if i >= len(tokens) or not tokens[i][1].startswith("- ") or tokens[i][0] == 0:
        return []
    rules, _ = parse_rules(tokens, i, 0)
    return rules


def parse_connectors(tokens):
    start = find_section(tokens, "connectors")
    if start is None:
        return []
    connectors = []
    i = start + 1
    while i < len(tokens) and not tokens[i][1].startswith("- "):
        if tokens[i][0] == 0:
            return connectors
        i += 1
    if i >= len(tokens):
        return connectors
    connector_indent = tokens[i][0]
    while i < len(tokens):
        indent, content, number = tokens[i]
        if indent != connector_indent or not content.startswith("- "):
            break
        connector = {
            "line": number,
            "slug": None,
            "provider": None,
            "url": None,
            "sensitive": "false",
            "rules": [],
            "policies_line": None,
            "policies_empty": False,
        }
        body = content[2:].strip()
        if body:
            key, value = split_key(body)
            if key:
                connector[key] = value
        i += 1
        while i < len(tokens):
            indent, content, number = tokens[i]
            if indent <= connector_indent:
                break
            if content.startswith("policies:"):
                connector["policies_line"] = number
                _, value = split_key(content)
                i += 1
                if value == "[]":
                    connector["policies_empty"] = True
                    continue
                if value:
                    connector["policies_empty"] = True
                    continue
                if i >= len(tokens) or tokens[i][0] <= indent or not tokens[i][1].startswith("- "):
                    connector["policies_empty"] = True
                    continue
                rules, i = parse_rules(tokens, i, indent)
                connector["rules"].extend(rules)
                continue
            key, value = split_key(content)
            if key:
                connector[key] = value
            i += 1
        connectors.append(connector)
    return connectors


def count(number, word):
    return "%d %s%s" % (number, word, "" if number == 1 else "s")


def is_regex(pattern):
    return len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/")


def is_relative_literal(pattern):
    """A plain action name: no dot, no glob, not a /regex/."""
    if is_regex(pattern) or any(ch in pattern for ch in GLOB_CHARS):
        return False
    return "." not in pattern


def check(text):
    """Return (connectors, rules, findings); findings are (line, message)."""
    tokens = tokenize(text)
    project_rules = parse_project_rules(tokens)
    connectors = parse_connectors(tokens)
    findings = []

    for rule in project_rules:
        match = rule["match"]
        if match and is_relative_literal(match):
            findings.append((
                rule["line"],
                'project-wide rule "%s" is relative; project-wide patterns are fully qualified, '
                'for example linear.%s' % (match, match),
            ))

    groups = [("project-wide", project_rules)]
    for connector in connectors:
        groups.append(('connector "%s"' % connector["slug"], connector["rules"]))

    for label, rules in groups:
        for rule in rules:
            match = rule["match"] or "(no match)"
            action = rule["action"]
            if not rule["match"]:
                findings.append((rule["line"], "%s rule has no match pattern" % label))
            if not action:
                findings.append((rule["line"], "%s rule %s has no action" % (label, match)))
            elif action not in ACTIONS:
                findings.append((
                    rule["line"],
                    '%s rule %s has action "%s"; use always_run, require_approval or block'
                    % (label, match, action),
                ))
            if len(rule["conditions"]) > MAX_CONDITIONS:
                findings.append((
                    rule["line"],
                    '%s rule %s has %d conditions; this check caps a rule at %d, and all must match'
                    % (label, match, len(rule["conditions"]), MAX_CONDITIONS),
                ))
            for condition in rule["conditions"]:
                if not condition["arg"]:
                    findings.append((
                        condition["line"],
                        "%s rule %s has a condition with no arg path" % (label, match),
                    ))
                negate = condition["negate"]
                if negate is not None and negate not in ("true", "false"):
                    findings.append((
                        condition["line"],
                        '%s rule %s has negate: %s; negate is a boolean, true or false'
                        % (label, match, negate),
                    ))

    for connector in connectors:
        slug = connector["slug"] or "(no slug)"
        if not connector["slug"]:
            findings.append((connector["line"], "connector has no slug"))
        elif connector["provider"] == "mcp" and not connector["url"]:
            findings.append((
                connector["line"],
                'connector "%s" is provider: mcp and has no url' % slug,
            ))
        if connector["policies_empty"]:
            findings.append((
                connector["policies_line"],
                'connector "%s" has an empty policies: list; remove the key or add a rule' % slug,
            ))
        if connector["sensitive"].lower() in ("true", "yes"):
            for rule in connector["rules"]:
                if rule["action"] == "always_run":
                    findings.append((
                        rule["line"],
                        'connector "%s" is sensitive: true but its own rule %s always runs; '
                        "sensitive holds every remaining action for approval, so this rule "
                        "removes that gate for the action it matches"
                        % (slug, rule["match"] or "(no match)"),
                    ))

    findings.sort()
    rule_count = len(project_rules) + sum(len(c["rules"]) for c in connectors)
    condition_count = sum(len(r["conditions"]) for r in project_rules) + sum(
        len(r["conditions"]) for c in connectors for r in c["rules"]
    )
    return connectors, rule_count, condition_count, findings


def main(argv):
    if len(argv) != 2:
        print("usage: python3 check_policies.py <kortix.yaml>", file=sys.stderr)
        return 2
    path = argv[1]

    print("Kortix evaluates each connector call in this order, and the first match wins:")
    for line in LEVELS:
        print("  " + line)
    print("")
    print("Source: " + SOURCE)

    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        print("\ncannot read %s: %s" % (path, error), file=sys.stderr)
        return 2

    connectors, rule_count, condition_count, findings = check(text)
    print("")
    print(
        "read %s, %s and %s from %s"
        % (
            count(len(connectors), "connector"),
            count(rule_count, "rule"),
            count(condition_count, "condition"),
            path,
        )
    )
    if findings:
        for line, message in findings:
            print("FAIL line %s: %s" % (line, message))
        print("%d fault(s) found in %s" % (len(findings), path))
        return 1
    print("PASS: every rule checked in %s is well formed" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
