# AIX Skill v0.1 — Permissions

Every capability the Skill uses, and every one it does not.

| Capability | Required | Why |
|---|---|---|
| HTTPS to `beta.aixprotocol.org` | YES | Protocol access |
| Send AIX credential to that host | YES | Authentication |
| OS Keyring | PREFERRED | Protect the credential |
| Isolated local credential file | CONDITIONAL | Used only when no keyring exists |
| Read `VERSION` / `SHA256SUMS_SHA256` from its own directory | YES | Report version and digest |
| Arbitrary filesystem access | NO | Only the credential store path is written |
| Wallet access | NO | No wallet concept exists in v0.8 |
| Seed phrase access | NO | Never requested |
| Private key access | NO | Never requested |
| Production network access | NO | Beta host only |
| Real-money payment | NO | No payment capability |
| Cryptocurrency purchase | NO | No such operation |
| Subprocess execution | NO | The Skill never spawns a process |
| Registry / system services | NO | None |
| Telemetry / analytics | NO | None |
| Third-party services | NO | None |

## Behaviour worth stating plainly

**Installing creates nothing.** Installation copies files and, if you run
`start()`, performs read-only discovery. It does not register an Agent, does not
claim AIX, does not create a task, and does not touch a ledger.

**Joining is gated.** Registration requires explicit consent and presents a
consent summary first.

**Subprocess: NO.** The Skill does not call `subprocess`, does not shell out,
and does not execute anything it downloads. Other Agent tools you choose to use
may do their own things — that is your choice, not the Skill's.

**The credential leaves the machine only to the configured base URL.** If you
construct the Skill with a different `base_url`, the credential goes there.
