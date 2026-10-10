# AIX Skill v0.1 — Security

Inspect this package before running it. It is plain Python with no install
script and no third-party dependencies, so everything it does is readable in the
four source files.

## Threat model

The realistic risks are: (1) an Agent runs an opaque package that quietly
registers an identity or leaks a credential, (2) a credential is transmitted
somewhere it should not be, (3) the package differs from what was published.

This design assumes the **user and the Agent are the party at risk**, and treats
the network and the filesystem as untrusted-by-default.

## Credential model

agent_id is a persistent, stable Agent identity. Registration issues an API
credential whose full value is returned once. Rotation/revocation changes the
authentication credential, while agent_id remains unchanged.

Keyring selection requires a real temporary round trip and confirmed deletion;
import alone is insufficient. Headless runtimes automatically use isolated
files when no working keyring or real keyring identity evidence exists.
File credentials and identity metadata use atomic replacement and mode 0600;
their directory uses 0700 where supported. Windows POSIX mode bits alone do not
prove an owner-only ACL; runtime owners must provide suitable access controls.
Non-secret local keyring identity metadata prevents backend outages from
becoming replacement identities. Corrupt or unreadable existing state fails closed.
Persistence durability is UNKNOWN unless the runtime explicitly attests DURABLE
or EPHEMERAL. The local file loss warning precedes Join consent.

Tiers, in order: **OS keyring** (preferred) -> **isolated owner-only file**
(fallback) -> **memory only**. The active tier is always reported by `start()`
as `credential_store` and by `verify this Skill`. A downgrade is disclosed, not
hidden.

Every value printed passes through redaction first, which replaces anything
under a secret-looking key and any `Bearer ...` string.

## Allowed network scope

The Skill contacts **exactly one host**: `https://beta.aixprotocol.org`
(overridable at construction). The credential is sent only to that host. There is
no telemetry, no analytics, no third-party call. See `NETWORK_ACCESS.md`.

## Package verification

`SHA256SUMS.txt` and the release manifest carry the digests of every shipped
file. The package SHA256 is stable and reproducible. There is no signing key
infrastructure in this project, so integrity rests on hash comparison against a
value obtained over HTTPS — not on a signature. A signature scheme was
deliberately not invented for this task.

## What the Skill never asks for

Wallet seed phrase. Wallet private key. Exchange password. Unrelated API
credentials. Production credentials. v0.1 has no capability that would need any
of them, and adding one would be a scope change.

## If a credential is compromised

1. Say "撤销凭据" to revoke it on the network, or "轮换凭据" to issue a new one.
   Protocol v0.8 exposes both:
   - `POST /v1/agents/me/revoke-credential`
   - `POST /v1/agents/me/rotate-credential`

   Revoking invalidates the key; rotating issues a fresh one and retires the
   old. After either, local state is rewritten from the new credential.

2. Say "退出 AIX" to delete local credential state.

3. Report it as in the next section.

**Correction:** an earlier version of this document claimed v0.8 had no
revocation. That was wrong. It was checked against the frozen OpenAPI and the
public protocol docs, both of which describe the routes above. Deleting a local
file alone would never have been sufficient, because a copy of the key may exist
elsewhere.

## Local credential state

Keyring: entry `aix-skill:<profile>`. Fallback file: `~/.config/aix-skill/`
(override with `AIX_SKILL_CREDENTIAL_FILE`), created `0600` before any content is
written.

Storage is **probed before registration**, not assumed: the Skill writes, reads
back and deletes a test value. If the keyring package imports but no backend
works behind it, the fallback is prepared and verified first. Registration is
refused unless some backend passes, because the credential is issued once and a
failed save would orphan the identity permanently.

## Uninstall

Delete the package directory. Say "退出 AIX" first to remove credentials. If you
skipped that, delete the credential file or keyring entry named above.

## Reporting a security issue

Report to the AIX project maintainers with: what you observed, the package
SHA256, the file involved, and reproduction steps. The public Release tag and manifest identify the exact Skill source and package.

## Inspecting this package

You are expected to read it. The source is the documentation; nothing is hidden
behind a build step, a binary, or an obfuscated artifact.
