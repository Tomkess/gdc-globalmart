# Publish targets

A *target* is one GoodData org this repo can publish GlobalMart into. Adding one is a
config entry plus an environment variable — never a code change.

## The two files

| File | Holds | Committed? |
|---|---|---|
| `config/targets.yaml` | host, org id, datasource id, schema, warehouse connection details | **yes** — none of it is secret |
| `.env` | one API token per target, plus warehouse secrets | **no** — gitignored; see `.env.example` |

A profile names the *environment variable* holding its warehouse secret
(`datasource_secret_env: MOTHERDUCK_TOKEN`), never the value. The token itself is resolved
from `GLOBALMART_TOKEN__<PROFILE_NAME_UPPER_SNAKE>`, so several orgs coexist in one `.env`
with nothing to edit between runs:

```
demo-cloud       -> GLOBALMART_TOKEN__DEMO_CLOUD
usecases-ai      -> GLOBALMART_TOKEN__USECASES_AI
local-inference  -> GLOBALMART_TOKEN__LOCAL_INFERENCE
```

A generic `GLOBALMART_TOKEN` exists as a fallback for a single-host setup. Prefer the
per-target variables once you have more than one org: with a shared token, a mistyped
`--target` authenticates successfully against the wrong org instead of failing.

## Publishing

```bash
# Rehearsal — reads, resolves, asserts, diffs. Writes nothing.
globalmart publish parent --target demo-cloud

# The same command, for real.
globalmart publish parent --target demo-cloud --apply
```

**Targets are owned by this repo.** `put_declarative_workspace` has REPLACE semantics: it
overwrites the workspace's entire content in one call. Anything authored in the UI and not
represented in `layouts/workspaces/globalmart/` is destroyed by a publish.

Three guards stand between a typo and that outcome (ADR 002):

1. **`--apply` is required.** Without it the command is a read-only rehearsal that prints
   the diff it would apply.
2. **The org is pinned.** The profile declares `organization_id`; if the host reports a
   different one, the publish refuses and names both. This is not theoretical — it fired
   during development and caught an org id inferred from a hostname.
3. **A backup runs immediately before the write**, to
   `backups/<target>/<workspace>/<UTC timestamp>/`, in the same YAML form as the repo. A
   rollback is therefore `globalmart publish parent --from backups/... --apply`.
   `--no-backup` is refused unless `--apply` is also present, and warns.

## Reading the report

```
changed : False
```

means the target already matches the repo. Server-owned fields (`createdAt`, `modifiedAt`,
`createdBy`, `modifiedBy`) are excluded from the comparison — the server stamps them on
every write, so including them made `changed` permanently `True` and buried real
differences under thousands of lines of noise. Measured against the live parent: 6849 diff
lines, all audit, zero real.

## Adding a target

1. **Put the token in `.env`**, named after the profile:

   ```
   GLOBALMART_TOKEN__USECASES_AI=<token for that org>
   ```

2. **Add a minimal profile** to `config/targets.yaml` — host is enough to start:

   ```yaml
   usecases-ai:
     host: https://usecases-ai.demo.cloud.gooddata.com
     organization_id: unknown          # filled in from step 3
     datasource_id: unknown
     datasource_schema: unknown
   ```

3. **Ask the host what it actually is**, rather than guessing:

   ```bash
   globalmart targets inspect --target usecases-ai
   ```

   It prints the organization id, every datasource with its type, schema and URL, and the
   existing workspaces — and flags a mismatch against what the profile claims. Guessing
   these is how `organization_id: petertomko`, inferred from a hostname, got into config
   during development when the org is really `gm-ddebmti`.

4. **Fill in the profile** from that output, and document the token variable in
   `.env.example` — a test asserts every profile has its variable documented there.

5. **Rehearse**, read the report, then `--apply`.

The portability contract: publishing the same repo state into two orgs must yield layouts
identical except for host, org, datasource id and schema. `tests/test_compare.py` asserts
this offline; FEAT-006 will assert it against two live orgs.
