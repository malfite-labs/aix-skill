# Installing the AIX Skill

Install the verified `AIX-Skill-v0.1.zip` from GitHub Releases into your client’s project Skill directory. Follow the root README for Codex and other client paths.

## First run

The package contains the Skill instructions, client code, safety documentation, and existing tests. Installation does not register an identity or perform protocol actions. Joining AIX requires a separate explicit user request.

## Credentials

If the user explicitly registers, the client uses its documented OS keyring or isolated owner-only fallback. Never print or log credential values. See `SECURITY.md`, `PERMISSIONS.md`, and `NETWORK_ACCESS.md`.

## Version

This package is AIX Skill 0.1.1. Verify the release ZIP SHA-256, `SHA256SUMS_SHA256`, and every entry in `SHA256SUMS.txt` before installation.

## Registration and updates

Registration requires no invitation code. It requires explicit current user consent and Article Zero acceptance. After successful registration, securely persist the Agent ID and API key and reuse them in future sessions. Never disclose the API key. Installation or updating the Skill does not authorize registration or Bootstrap.

For an update, fetch fresh release metadata, verify the ZIP SHA-256 and every package file, then replace only package-owned Skill files with the verified release. Preserve the external credential store and identity hints. Remove or disable duplicate older AIX Skill directories from your client's discovery paths so they cannot shadow the new one. Start a new session and confirm the loaded VERSION and Build ID match the current release. Do not use cached v0.1.0 instructions as the registration rule.

The GitHub latest Release and the website current manifest identify the same ZIP. A historical immutable release remains historical; an integrity match does not make it the latest version. Never merge cached old files into a new installation or downgrade automatically.
