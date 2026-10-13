# Import a subscription

Start from a working [initialized runtime](setup.md). Keep subscription YAML or a URL in a private directory (`chmod 700`) and a private file (`chmod 600`). URLs may contain credentials: never put them in argv, screenshots or logs. Only HTTPS URLs are accepted.

```bash
chmod 700 "$HOME/private"
chmod 600 "$HOME/private/subscription.yaml"
mihomoctl subscription preview --source-file "$HOME/private/subscription.yaml" --policy nodes --json
```

Alternatives: `--url-file "$HOME/private/subscription-url"`, or pipe content into `subscription preview --stdin`. Choose exactly one source. `auto` selects provider mode when routing policy is present, otherwise nodes. `nodes` imports nodes while retaining local groups and routing rules; it does not create a selection group. `provider` can replace allowed provider/group/routing fields; review the changed keys. It cannot overwrite authentication, listeners or controller credentials.

Preview is private and does not activate configuration or restart the runtime. Read the reported candidate policy, changed fields, validation and candidate SHA256. The public JSON envelope wraps controller output under `data.legacy`; the preview fields are `data.legacy.id` and `data.legacy.sha256`. Copy the reviewed ID and digest:

```bash
mihomoctl subscription apply PREVIEW_ID --sha256 CANDIDATE_SHA256
mihomoctl config validate
mihomoctl restart
```

Apply verifies the original active-config digest, the candidate SHA256 and the allowed changed fields, validates with the managed core, then backs up and saves. Original-config drift, candidate tampering, forbidden fields or validation failure refuse activation. Start a fresh preview after any configuration change. Review custom rules again after later provider imports, which may replace routing policy. Never hand-edit a saved preview to bypass these gates.
