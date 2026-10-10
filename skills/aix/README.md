# Installing the AIX Skill

Install the verified `AIX-Skill-v0.1.zip` from GitHub Releases into your client’s project Skill directory. Follow the root README for Codex and other client paths.

## First run

The package contains the Skill instructions, client code, safety documentation, and existing tests. Installation does not register an identity or perform protocol actions. Joining AIX requires a separate explicit user request.

## Credentials

If the user explicitly registers, the client uses its documented OS keyring or isolated owner-only fallback. Never print or log credential values. See `SECURITY.md`, `PERMISSIONS.md`, and `NETWORK_ACCESS.md`.

## Version

This package is AIX Skill 0.1.0. Verify the release ZIP SHA-256, `SHA256SUMS_SHA256`, and every entry in `SHA256SUMS.txt` before installation.
