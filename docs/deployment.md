# Deployment

`api-contract` is a development and CI tool. It is not part of your running
service and should not be imported by it.

## Where it runs

| Place | What to run | Notes |
|---|---|---|
| Developer machine | `api-contract check` | Fast feedback before pushing. |
| Pull-request CI | `api-contract check --against origin/main`, or the [GitHub Action](ci.md#github-action) | The gate. Needs your app's dependencies installed, because the loader imports the app. |
| Scheduled job | `api-contract expiring --within 14d --fail` | Reminds you before allowlist entries expire; see [CI](ci.md#allowlist-expiry-reminders). |
| Release pipeline | `api-contract snapshot` on the release branch, committed | Refreshes the snapshot once a change is intentional. |

Do not install it in the production image. Keep it in a dev or CI dependency
group and pin it (`api-contract==0.1.0a2`) so a new release cannot change a
build's result unannounced.

## CI checklist

- Check out with enough history for `--against` (`fetch-depth: 0`, or fetch the
  target branch).
- Install your project and `api-contract` in the same environment.
- Use dummy values for secrets and point databases at nothing: loading the
  schema must not need live services. See
  [Troubleshooting](troubleshooting.md).
- Commit `api-contract.json` and the allowlist; review changes to them like code.
- Run with read-only repository permissions; only the PR-comment step needs
  write access. See [Security](security.md#running-it-in-ci-safely).

## Offline and air-gapped builds

Nothing is fetched at run time. Use a `file:` source if the app cannot be
imported in the build environment, and publish the generated spec as a build
artifact.
