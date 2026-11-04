# MCP connector policy examples for Kortix, the open-source CompanyOS

Kortix is an open-source CompanyOS — your agents, skills, company memory, and connectors in one git repo you own.

This repo is one `kortix.yaml` with three MCP connectors and the policy rules that decide what each one may do, plus a small checker that fails when a rule is malformed. Most MCP setup stops at connecting the server. What decides whether a call runs is the rule that matches it, the account it runs as, and the argument conditions that make the rule specific. That file gets written by hand in every project, usually after the first incident, so here it is written once and checked.

The manifest never holds a credential. Connector credentials are brokered server-side and never enter the machine.

## What the example shows

- Three `provider: mcp` connectors, `linear`, `notion` and `sentry`, each with its `url` and a `transport` of `http` (the default) or `sse`.
- `sentry` is `sensitive: true`: every remaining action needs approval, reads included.
- A project-wide `*.delete*` rule blocks delete actions on every connector.
- One argument condition on `notion`: `create_page` runs without asking only when `parent.database_id` matches an allowlisted value. A call that leaves the argument out does not satisfy the condition, so it falls through to `require_approval`.
- `agents.triage.connectors` grants all three connectors to one agent.

## Four levels, first match wins

Kortix evaluates each call in this order, and the first rule that matches decides. The levels below it never run.

1. **Project-wide `policies:` in `kortix.yaml`.** Patterns are fully qualified. Here, `*.delete*` blocks and `linear.create_issue` asks first. A set or a base rule cannot loosen a project rule.
2. **The calling agent's policy set on that connector (`agents.<name>.policy_sets`).** A set can loosen a base rule for its agent. Here, `agents.triage` binds no set, so this level has nothing to match.
3. **The connector's own `policies:`, the base rules.** Patterns are relative to the connector. Here, `notion` runs `read_*` without asking.
4. **No rule matched.** A `sensitive: true` connector holds the call for approval, reads included. Otherwise `policy.default_mode` decides: here it is `allow_all`, the default, so the call runs. Approval gates you set. Off until you set them, so the rules in this file are the whole gate.

## Three calls traced through the file

A call to `linear.delete_issue` hits level 1 and stops. The project-wide `*.delete*` rule blocks it, no agent set or connector rule is consulted, and the caller gets a denial instead of a result.

A call to `notion.create_page` with `parent.database_id` set to `3f2a1c9e` matches the connector's `create_page` rule at level 3, and its one condition holds, so it runs. The same call without that path does not match the `create_page` rule, because every condition must hold, and falls to the connector's `*` rule, which asks for approval. Change the argument to another database and it asks as well: an approval covers one exact request, so the earlier approval does not carry over.

A call to `sentry.list_events` has no rule of its own, so level 4 decides. `sensitive: true` holds it for approval even though it is a read.

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
  2. the calling agent's policy set:          agents.<name>.policy_sets
  3. the connector's own policies:            relative, e.g. send_*
  4. no rule matched: sensitive: true holds the call; else policy.default_mode

Source: https://kortix.com/docs/developers#connector-rules-and-approvals

read 3 connectors, 8 rules and 1 condition from kortix.yaml
PASS: every rule checked in kortix.yaml is well formed
```

It exits 0.

Output for `kortix.yaml.broken`, which carries two deliberate faults:

```text
Kortix evaluates each connector call in this order, and the first match wins:
  1. project-wide policies: in kortix.yaml   fully qualified, e.g. gmail.send_email
  2. the calling agent's policy set:          agents.<name>.policy_sets
  3. the connector's own policies:            relative, e.g. send_*
  4. no rule matched: sensitive: true holds the call; else policy.default_mode

Source: https://kortix.com/docs/developers#connector-rules-and-approvals

read 2 connectors, 5 rules and 0 conditions from kortix.yaml.broken
FAIL line 17: project-wide rule "create_issue" is relative; project-wide patterns are fully qualified, for example linear.create_issue
FAIL line 39: connector "sentry" is sensitive: true but its own rule list_events always runs; sensitive holds every remaining action for approval, so this rule removes that gate for the action it matches
2 fault(s) found in kortix.yaml.broken
```

It exits 1.

## What the checker checks

- A project-wide pattern with no dot: a relative name where a fully qualified `<slug>.<action>` belongs. Globs and `/regex/` patterns are left alone, since `*.delete*` is a valid project-wide pattern.
- `sensitive: true` on a connector that also carries an `always_run` rule of its own. That rule wins at level 3 and removes the approval gate the connector is set up for.
- A `negate` value that is not `true` or `false`, caught before a call does.
- A connector with an empty `policies:` list, a rule with no `match` or no `action`, an `action` outside `always_run`, `require_approval` and `block`, and a `provider: mcp` connector with no `url`.

It reads lines and indentation, and it looks only at the fields above. It is not a YAML parser, so a document that is valid YAML but laid out differently from this example can be misread. It does not load the file into Kortix, does not validate the file against a project, does not check that a URL resolves or an action exists on the server, and does not run any policy. Treat a pass as "these rules are well formed", nothing more.

## Approvals you will hit

- An approval covers one exact request: the same connector, action, arguments and account. Change an argument and it needs a new approval. A caller with a project-scoped token repeats nothing: the call runs on approval. A script with any other token must send the same call again within 15 minutes after approval.
- A held call expires when nobody decides it within 24 hours, or within the project's `approvals.ttl`. The session does not resume, and the agent asks again with a new call.
- A private account works only in its owner's private sessions. A shared account covers the project and every agent whose grant names the connector. An unattended run never uses a private account.

## Where to read more

- [Which permissions apply when an agent calls a connector](https://mcpconnectorsguide.com/whose-permissions-apply)
- [What an agent can see through a connector](https://mcpconnectorsguide.com/what-can-an-agent-see)
- [Running several MCP servers in one project](https://mcpconnectorsguide.com/multiple-mcp-servers), for what changes when one agent holds connectors to more than one server and where the servers' rules meet.
- [MCP connector vs MCP server](https://mcpconnectorsguide.com/mcp-connector-vs-mcp-server), for which half of a call each side owns: the server publishes the tools, the connector entry in your repo carries the rule.
- [Kortix connector docs](https://kortix.com/docs/guide#connectors), for the provider table, the account rules and the full policy reference.

## A note on scope

This repo is an example, not a feature list. `check_policies.py` is a script in this repo, not a Kortix tool, and Kortix does not ship it. The server URLs are illustrative and named after each server's domain, so check the vendor's docs before you paste one into a real project.
