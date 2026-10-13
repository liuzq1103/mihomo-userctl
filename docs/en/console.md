# Console

`mihomoctl tui` chooses Textual when installed and otherwise a plain terminal menu. Select `mihomoctl tui --engine plain` explicitly if desired. Textual is optional: install the release tui extra or verified dependencies into the interpreter used by your controller. The console never implicitly downloads a Python environment.

Subscription/rule/policy operations use the same manager, core path and safety gates. See [subscriptions](subscriptions.md), [rules](rules.md) and [CLI reference](reference/cli.md). JS overrides execute trusted code; Node vm is not a sandbox.
