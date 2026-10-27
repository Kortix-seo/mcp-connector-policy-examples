# MCP connector policy examples for Kortix, the open-source AI Operating System

Kortix is the open-source AI Operating System. Your agents, skills, company memory, and connectors live in one git repo you own.

This repo is one `kortix.yaml` with three MCP connectors and the policy rules that decide what each one may do, plus a small checker that fails when a rule is malformed. Most MCP setup stops at connecting the server. What decides whether a call runs is the rule that matches it, the account it runs as, and the argument conditions that make the rule specific. That file gets written by hand in every project, usually after the first incident, so here it is written once and checked.

The manifest never holds a credential. Connector credentials are brokered server-side and never enter the machine.

## What the example shows

- Three `provider: mcp` connectors, `linear`, `notion` and `sentry`, each with its `url` and a `transport` of `http` (the default) or `sse`.
- `sentry` is `sensitive: true`: every remaining action needs approval, reads included.
- A project-wide `*.delete*` rule blocks delete actions on every connector.
- One argument condition on `notion`: `create_page` runs without asking only when `parent.database_id` matches an allowlisted value. A call that leaves the argument out never matches, so it falls through to `require_approval`.
- `agents.triage.connectors` grants all three connectors to one agent.

## Four levels, first match wins

Kortix evaluates each call in this order, and the first rule that matches decides. The levels below it never run.

1. **Project-wide `policies:` in `kortix.yaml`.** Patterns are fully qualified. Here, `*.delete*` blocks and `linear.create_issue` asks first. A connector rule cannot override these.
2. **The connector's own `policies:`.** Patterns are relative to the connector. Here, `notion` runs `read_*` without asking.
3. **`sensitive: true` on the connector.** Here, `sentry` holds every remaining action for approval, reads included.
4. **`policy.default_mode`.** Here it is `allow_all`, the default, so every action the three levels above did not match runs. Approval gates you set. Off until you set them, so the rules in this file are the whole gate.

## Three calls traced through the file

A call to `linear.delete_issue` hits level 1 and stops. The project-wide `*.delete*` rule blocks it, no connector rule is consulted, and the caller gets a denial instead of a result.

A call to `notion.create_page` with `parent.database_id` set to `3f2a1c9e` matches the connector's `create_page` rule at level 2, and its one condition holds, so it runs. The same call without that path matches nothing at level 2, because a missing argument never matches a condition, and falls to the connector's `*` rule, which asks for approval. Change the argument to another database and it asks as well: an approval covers one exact request, so the earlier approval does not carry over.

A call to `sentry.list_events` has no rule of its own, so level 3 decides. `sensitive: true` holds it for approval even though it is a read.

That is the whole reason to keep this in git. A reader can see, in one file, that a delete is blocked everywhere, that one Notion write skips the queue only with an allowlisted parent, and that everything on Sentry waits for a person.

## Run the checker

Python 3, standard library only, no network calls.

```sh
python3 check_policies.py kortix.yaml
python3 check_policies.py kortix.yaml.broken
```

Output for the working file:

```text
Kortix evaluates each connector call in this order, and the first match wins:
  1. project-wide policies: in kortix.yaml   fully qualified, e.g. gmail.send_email
  2. the connector's own policies:            relative, e.g. send_*
  3. sensitive: true on the connector         every remaining action needs approval, reads included
  4. policy.default_mode                      allow_all, the default, or risk

Source: https://kortix.com/docs/connect/connectors#policies-and-approvals

read 3 connectors, 8 rules and 1 condition from kortix.yaml
PASS: every rule checked in kortix.yaml is well formed
```

It exits 0.

Output for `kortix.yaml.broken`, which carries two deliberate faults:

```text
Kortix evaluates each connector call in this order, and the first match wins:
  1. project-wide policies: in kortix.yaml   fully qualified, e.g. gmail.send_email
  2. the connector's own policies:            relative, e.g. send_*
  3. sensitive: true on the connector         every remaining action needs approval, reads included
  4. policy.default_mode                      allow_all, the default, or risk

Source: https://kortix.com/docs/connect/connectors#policies-and-approvals

read 2 connectors, 5 rules and 0 conditions from kortix.yaml.broken
FAIL line 17: project-wide rule "create_issue" is relative; project-wide patterns are fully qualified, for example linear.create_issue
FAIL line 39: connector "sentry" is sensitive: true but its own rule list_events always runs; sensitive holds every remaining action for approval, so this rule removes that gate for the action it matches
2 fault(s) found in kortix.yaml.broken
```

It exits 1.

## What the checker checks

- A project-wide pattern with no dot: a relative name where a fully qualified `<slug>.<action>` belongs. Globs and `/regex/` patterns are left alone, since `*.delete*` is a valid project-wide pattern.
- `sensitive: true` on a connector that also carries an `always_run` rule of its own. That rule wins at level 2 and removes the approval gate the connector is set up for.
- More than 10 conditions on one rule. A rule holds up to 10, and all of them must match.
- A `negate` value that is not `true` or `false`. A malformed condition fails closed in Kortix, and this check catches it before a call does.
- A connector with an empty `policies:` list, a rule with no `match` or no `action`, an `action` outside `always_run`, `require_approval` and `block`, and a `provider: mcp` connector with no `url`.

It reads lines and indentation, and it looks only at the fields above. It is not a YAML parser, so a document that is valid YAML but laid out differently from this example can be misread. It does not load the file into Kortix, does not validate the file against a project, does not check that a URL resolves or an action exists on the server, and does not run any policy. Treat a pass as "these rules are well formed", nothing more.

## Approvals you will hit

- An approval covers one exact request: the same connector, action, arguments and account. Change an argument and it needs a new approval. An identical repeat within 15 minutes runs once.
- A held call expires when nobody decides it within 24 hours, or within the project's `approvals.ttl`. The session does not resume, and the agent asks again with a new call.
- A call that names no account is used only when the choice is certain: exactly one account is reachable, or exactly one is pinned as the default. Otherwise it is denied with `account_required` and `available_accounts`, and Kortix never substitutes another account.

## Where to read more

Three pages of an independent guide go with this file. [Which permissions apply when an agent calls a connector](https://mcpconnectorsguide.com/whose-permissions-apply) works through the account choice that the first three levels above never settle. [What an agent can see through a connector](https://mcpconnectorsguide.com/what-can-an-agent-see) separates what a server publishes from what one agent may call.

A project that adds more than one connector has to settle [how several MCP servers fit together](https://mcpconnectorsguide.com/multiple-mcp-servers): colliding tool names, scattered rules and per-agent grants are what break first. The line between [an MCP server and the connector that carries its rule](https://mcpconnectorsguide.com/mcp-connector-vs-mcp-server) is the line between someone else's software and this file, and on Claude, [a Claude connector and the account behind it](https://mcpconnectorsguide.com/claude-mcp-connectors) are configured on three different surfaces, none of which is the manifest. The [Kortix connector docs](https://kortix.com/docs/connect/connectors) remain the reference for the provider table, the account rules and the full policy reference.

## A note on scope

This repo is an example, not a feature list. `check_policies.py` is a script in this repo, not a Kortix tool, and Kortix does not ship it. The server URLs are illustrative and named after each server's domain, so check the vendor's docs before you paste one into a real project.
