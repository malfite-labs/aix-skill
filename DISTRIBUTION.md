# AIX Skill v0.2.4 frozen source and release verification

Build `skill-0.2.4-86760e556700` uses Protocol source `86760e556700fc7bc1764e730595cf39a533a2aa`. Frozen ZIP SHA256 is `d06c4443d311abe7d64db970e44f2e894ca581e370e0f0348b36cec9e856edc8`. The public package snapshot is recorded in [V0_2_4_PROVENANCE.json](https://github.com/malfite-labs/aix-skill/blob/main/V0_2_4_PROVENANCE.json); its commit is distinct from the Protocol build commit. Every one of the 29 ZIP members maps byte-for-byte to `skills/aix/<relative path>` at that immutable public commit, including generated checksums and metadata.

## Independent verification

Clone this repository and download `AIX-Skill-v0.1.zip` from the official v0.2.4 GitHub Release or website. Before public cutover, the authorized operator must verify staged assets and may not claim public verification succeeded.

```sh
python tools/verify_frozen_source.py --zip /path/to/AIX-Skill-v0.1.zip --record V0_2_4_PROVENANCE.json
```

Expected: PASS, 29 files, SHA256 `d06c4443d311abe7d64db970e44f2e894ca581e370e0f0348b36cec9e856edc8`. The verifier compares actual ZIP bytes with immutable Git blobs, not working-tree files or README assertions. Independently download GitHub's source archive at the full public commit and compare `skills/aix` members with the same ZIP/hash map. Do not repack a source archive and expect identical ZIP bytes.

## Publication gate

Follow [SKILL_RELEASE_RULE.md](SKILL_RELEASE_RULE.md). Public source, correct immutable Tag, formal GitHub Release, website ZIP/manifest, and README/CHANGELOG/install docs must agree. GitHub and website actual ZIP downloads must equal the frozen hash. Do not modify frozen ZIP metadata in place or publish on missing evidence. Git+hash provenance is not an independent digital signature.

Only allowlisted public Skill code, instructions, package tests and integrity metadata are mirrored. No server code, internal deployment configuration, keys, tokens, Agent identities, databases or transaction data belong here. Updates preserve separate identity/credential stores and unrelated user files.

## Historical artifacts

Existing Tags, Releases and V0_2_0/V0_2_1/V0_2_3 provenance records remain unchanged. They describe their own immutable artifacts and are not evidence for v0.2.4. Universal Delivery remains available; Creator input retention is independent from Worker output retention.
