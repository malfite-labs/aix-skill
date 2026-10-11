# Distribution and provenance

The immutable GitHub Release `v0.1.1` is the canonical versioned GitHub package. The Release includes `AIX-Skill-v0.1.zip` and `release-manifest.json`.

The release manifest is generated after tagging and identifies the repository commit targeted by `v0.1.1`, the package Build ID, ZIP SHA-256, and per-file hashes. It omits any unverifiable upstream source commit. The release tag, commit, manifest, and downloadable ZIP can all be checked independently from this public repository.

The website current manifest and the GitHub latest Release distribute the same immutable ZIP and Build ID. Verify the current metadata before selecting an artifact; a historical pinned tag is not an update check. Existing v0.1.0 packages remain historical and are superseded by v0.1.1. Updates replace package-owned files only, preserve identity state, and require disabling duplicate older discovery directories.

## Client verification

Codex public-download installation is tested against a clean temporary project. Claude Code and Harness are marked NOT_TESTED unless an installed, named client can be exercised in the release environment.

## Scope

This repository distributes only AIX Skill instructions, client code, docs, existing package tests, and integrity/release assets. It does not publish AIX protocol server source, ledgers, databases, deployment configuration, Cloudflare details, internal tools, credentials, or website backend source.
