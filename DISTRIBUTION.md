# Distribution and provenance

The immutable GitHub Release `v0.1.0` is the canonical versioned GitHub package. The Release includes `AIX-Skill-v0.1.zip` and `release-manifest.json`.

The release manifest is generated after tagging and identifies the repository commit targeted by `v0.1.0`, the package Build ID, ZIP SHA-256, and per-file hashes. It omits any unverifiable upstream source commit. The release tag, commit, manifest, and downloadable ZIP can all be checked independently from this public repository.

The website distribution is a separate download endpoint. Its SHA-256 is compared to the GitHub Release asset during release verification; a difference is reported rather than described as parity. Older immutable website releases remain the website operator’s responsibility.

## Client verification

Codex public-download installation is tested against a clean temporary project. Claude Code and Harness are marked NOT_TESTED unless an installed, named client can be exercised in the release environment.

## Scope

This repository distributes only AIX Skill instructions, client code, docs, existing package tests, and integrity/release assets. It does not publish AIX protocol server source, ledgers, databases, deployment configuration, Cloudflare details, internal tools, credentials, or website backend source.
