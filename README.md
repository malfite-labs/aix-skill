# AIX Skill

Portable client Skill for AIX Protocol. This public repository contains only the Skill package, its documentation, existing tests, and release integrity metadata. It does not contain the protocol service, ledger, deployment configuration, or website backend.

## Install v0.1.0

Download the immutable [AIX Skill v0.1.0 Release](https://github.com/malfite-labs/aix-skill/releases/tag/v0.1.0). Verify the ZIP against the Release `release-manifest.json` SHA-256 before extraction. Then verify the package’s checksum manifest and all files.

Codex project install (PowerShell):

```powershell
$destination = Join-Path (Get-Location) '.agents\skills\aix'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item '.\AIX-Skill-v0.1\*' $destination -Recurse -Force
```

Codex project install (macOS/Linux):

```sh
mkdir -p .agents/skills/aix
cp -R AIX-Skill-v0.1/. .agents/skills/aix/
```

Claude Code’s conventional project path is `.claude/skills/aix`; runtime behavior should be checked for the specific client version. Harness has not been tested for this release.

## Contents and checks

The package includes the complete `SKILL.md`, client modules, references, existing tests, trust/security documentation, and integrity manifests under [`skills/aix`](skills/aix/). No extra runtime dependency is required; `keyring` is optional.

The public release manifest records the source repository, tag target commit, build ID, package SHA-256, and payload file hashes. `source_commit` refers to this repository’s release commit.

## Website distribution

The corresponding website download is available at [skill.aixprotocol.org](https://skill.aixprotocol.org/). Website byte parity is recorded in the release manifest only after comparing the actual downloaded archive.

Copyright 2026 Malfite Labs. Licensed under Apache-2.0. See [LICENSE](LICENSE).
