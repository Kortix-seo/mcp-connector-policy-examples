# MCP connector policy examples for Kortix, the open-source CompanyOS

Kortix is an open-source CompanyOS — your agents, skills, company memory, and connectors in one git repo you own.

This repo is one `kortix.yaml` with three MCP connectors and the policy rules that decide what each one may do, plus a small checker that fails when a rule is malformed. Most MCP setup stops at connecting the server. What decides whether a call runs is the rule that matches it, the account it runs as, and the argument conditions that make the rule specific. That file gets written by hand in every project, usually after the first incident, so here it is written once and checked.

The manifest never holds a credential. Connector credentials are brokered server-side and never enter the machine.

## What the example shows

- Three `provider: mcp` connectors, `linear`, `notion` and `sentry`, each with its `url` and a `transport` of `http` (the default) or `sse`.
- `sentry` is `sensitive: true`: every remaining action needs approval, reads included.
- A project-wide `*.delete*` rule blocks delete actions on every connector.
- One argument condition on `notion`: `create_page` runs without asking only when `parent.database_id` matches an allowlisted value. A call that leaves the path out does not satisfy the condition, so it falls through to `require_approval`.
- `agents.triage.connectors` grants all three connectors to one agent.

A fourth server is another entry in the same list. What changes when several MCP servers run in one project is where their tool names, rules and grants meet, and a `slug` per entry keeps each answer local to its server.

## Four levels, first match wins

Kortix decides each call in this order, and the first rule that matches decides. The levels below it never run. The order is documented under [connector rules and approvals](https://kortix.com/docs/developers#connector-rules-and-approvals).

1. **The project's `policies:`.** Patterns are fully qualified over `<slug>.<tool>`. Here, `*.delete*` blocks and `linear.create_issue` asks.
2. **The calling agent's policy set on that connector (`agents.<name>.policy_sets`).** A set is a named group of rules on one connector, given to one agent, and [registries and grants](https://kortix.com/docs/developers#registries-and-grants) has the syntax. This example defines no set and binds none, so level 2 never decides here.
3. **The connector's own `policies:`, the base rules.** Patterns are relative to the connector. Here, `notion` runs `read_*` without asking.
4. **No rule matched.** A `sensitive: true` connector holds the call for approval, reads included, so `sentry` holds every remaining action. Otherwise `policy.default_mode` decides: here `allow_all`, the default, so whatever the rules above did not match runs.

A set or a base rule cannot loosen a project rule. A set can loosen a base rule for its agent. A set the connector does not define blocks every call of that agent on it.

Approval gates you set. Off until you set them, so the rules in this file are the whole gate.

## Three calls traced through the file

A call to `linear.delete_issue` hits level 1 and stops. The project-wide `*.delete*` rule blocks it, no connector rule is consulted, and the caller gets a denial instead of a result.

A call to `notion.create_page` with `parent.database_id` set to `3f2a1c9e` matches the connector's `create_page` rule at level 3, and its one condition holds, so it runs. The same call without that path matches nothing at level 3, and falls through to the connector's `*` rule, which asks for approval. Change the argument to another database and it asks as well: an approval covers one exact action, so the earlier approval does not carry over.

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
  2. the calling agent's policy set          agents.<name>.policy_sets, on that connector
  3. the connector's own policies:           relative, e.g. send_*, the base rules
  4. no rule matched                         sensitive holds the call, else policy.default_mode

Source: https://kortix.com/docs/developers#connector-rules-and-approvals

read 3 connectors, 8 rules and 1 condition from kortix.yaml
PASS: every rule checked in kortix.yaml is well formed
```

It exits 0.

Output for `kortix.yaml.broken`, which carries two deliberate faults:

```text
Kortix evaluates each connector call in this order, and the first match wins:
  1. project-wide policies: in kortix.yaml   fully qualified, e.g. gmail.send_email
  2. the calling agent's policy set          agents.<name>.policy_sets, on that connector
  3. the connector's own policies:           relative, e.g. send_*, the base rules
  4. no rule matched                         sensitive holds the call, else policy.default_mode

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
- More than 10 conditions on one rule. The cap belongs to the checker, not to Kortix: the docs put no limit on conditions, and say every condition a rule carries must hold.
- A `negate` value that is not `true` or `false`. Each condition is `{ arg, match, negate }`, and `negate: true` inverts the match.
- A connector with an empty `policies:` list, a rule with no `match` or no `action`, an `action` outside `always_run`, `require_approval` and `block`, and a `provider: mcp` connector with no `url`.

It reads lines and indentation, and it looks only at the fields above. It is not a YAML parser, so a document that is valid YAML but laid out differently from this example can be misread. It does not load the file into Kortix, does not validate the file against a project, does not check that a URL resolves or an action exists on the server, and does not run any policy. Treat a pass as "these rules are well formed", nothing more.

## Approvals you will hit

- An approval covers one exact action: the same connector, action, arguments and account. A changed detail needs a new approval. An approval runs the action once, the agent does not send it again, and Kortix checks the project's rules again when it runs it, so a Block rule still wins.
- A caller with a project-scoped token repeats nothing: the call runs on approval. A script with any other token must send the same call again within 15 minutes after approval.
- A held action expires when nobody decides within 24 hours, unless the project sets a different `ttl` under `approvals:`. A project manager, or the person who started the session, decides, and there is no "approve everything for this session": an action that must run unattended needs an Allow rule.
- Every call runs as one account. A private account belongs to one person and works only in that person's own sessions, which is the default; a shared account belongs to the project, and every member and every allowed agent can use it. Automations never use a private account, so an unattended run needs a shared one. If you need the identity the provider actually sees, [which permissions apply when an agent calls a connector](https://mcpconnectorsguide.com/whose-permissions-apply) follows one call from the prompt to the request.

## Where to read more

- [Kortix connector guide](https://kortix.com/docs/guide#connectors), for what a connector is, who can use an account, and what Allow, Ask and Block do.
- [The kortix.yaml reference](https://kortix.com/docs/developers#connectors-keys), for the connector entry keys, the policy keys and the four levels.
- [A full v3 example project](https://kortix.com/docs/developers#example-project), for a whole manifest with a policy set and the agent bound to it.

## A note on scope

This repo is an example, not a feature list. `check_policies.py` is a script in this repo, not a Kortix tool, and Kortix does not ship it. The server URLs are illustrative and named after each server's domain, so check the vendor's docs before you paste one into a real project.
