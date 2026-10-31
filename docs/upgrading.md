# Upgrading

## Before you upgrade

1. Read the [changelog](https://github.com/Pythondeveloper6/api-contract/blob/main/CHANGELOG.md)
   entries between your version and the new one, especially **Changed** and
   **Deprecated**.
2. Read the [stability policy](stability.md): until 1.0 a minor release may make
   documented breaking changes, and patch releases never do.

## Steps

```bash
pip install --pre --upgrade api-contract      # pre-releases need --pre
api-contract snapshot --upgrade               # only if check says the snapshot is old
api-contract check                            # should print what it printed before
```

- **Snapshots.** Newer versions read older snapshots. `snapshot --upgrade`
  rewrites one in the current format without loading your app. An older
  version refuses a newer snapshot with an upgrade hint instead of misreading it.
- **Allowlists.** Change ids and kinds are stable. A renamed kind or key keeps
  working for at least one minor release and prints a warning naming the
  replacement.
- **New findings.** A release may report a change an earlier one missed. Review
  it as a normal finding, or allow it with a reason.
- **Rolling back.** Pin the previous version. The snapshot format only moves
  forward when you run `snapshot --upgrade`, so keep that change in its own commit.

## Pre-release series

Releases are `0.1.0aN` alphas. Pin an exact version in CI and upgrade on purpose.
