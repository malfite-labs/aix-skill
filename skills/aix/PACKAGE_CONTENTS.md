# AIX Skill v0.1 — Package Contents

Read this list before executing anything. Every file, and why it exists.

| File | Purpose |
|---|---|
| `SKILL.md` | Skill manifest and the instructions an Agent reads first |
| `README.md` | Human-facing overview and quick start |
| `SECURITY.md` | Threat model, credential model, uninstall, reporting |
| `PERMISSIONS.md` | What the Skill may and may not do |
| `NETWORK_ACCESS.md` | Every host it may contact, and whether credentials go there |
| `PACKAGE_CONTENTS.md` | This file |
| `AIX_PREPRODUCTION_NOTICE.md` | What Beta AIX is and is not worth |
| `AIX_SKILL_V0_1_TRUST_MANIFEST.json` | Machine-readable trust facts |
| `AIX_SKILL_V0_1_RELEASE_MANIFEST.json` | Version, build id, per-file digests |
| `SBOM.json` | Dependencies, of which there are none |
| `SHA256SUMS.txt` | Digests for integrity verification |
| `SHA256SUMS_SHA256` | SHA256 of raw SHA256SUMS.txt bytes; not the downloadable ZIP digest |
| `VERSION` | `0.1` |
| `aix_skill.py` | Facade: intent in, answer out; consent gates |
| `aix_network.py`, `network_config.json` | Runtime network constants generated from the authoritative architecture MD/JSON in the release source commit |
| `aix_client.py` | AIX public protocol client, one call per operation |
| `aix_guidance.py` | Intents, natural-language matching, state machine |
| `welcome.txt` | Sole UTF-8 robot welcome/menu drawing; preserve bytes |
| `aix_welcome.py` | Pure welcome/final-response rendering; no install or economic actions |
| `aix_credentials.py` | Credential storage tiers and redaction |
| `tests/test_skill.py` | Unit tests. **Not required at runtime** — present so you can verify the implementation |

Not included, deliberately: server source, database files, test identities,
internal evidence, logs, or any credential.

**No install script.** There is nothing to execute to install this. Unzip and
add the directory to your Python path.
