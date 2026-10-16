# Frozen v0.2.3 source provenance

The immutable source snapshot is `2a8259b5019eefbe916c009ca1abfa524f1283db` in this public repository.
Every29 file of frozen `AIX-Skill-v0.1.zip` maps to `skills/aix/<relative ZIP path>` at that commit,
including generated metadata and checksums. `V0_2_3_PROVENANCE.json` lists every SHA256.
Other repository tests and LICENSE are not package inputs. No newline normalization is applied during comparison.

Build ID `skill-0.2.3-f0df474e637c` identifies original protocol build input
`f0df474e637cbc1ca3eeb805a4d23a62e467777a`, not this public mirror commit.
Protocol merge `4155bcea068dadc5503cb030f2d7ce85cc5b04ec` contains identical package inputs.
The ZIP is unchanged; no self-referential source commit was injected into its frozen metadata.

## Independent verification

Clone this repository with Git. Obtain the frozen ZIP from the release operator; before formal publication
there is no promised public v0.2.3 ZIP URL. After separately authorized publication use that immutable URL.
Run (Python stdlib and Git only):

```sh
python tools/verify_frozen_source.py --zip /path/to/AIX-Skill-v0.1.zip
```

Expected: PASS,29 files, source commit2a8259b5019eefbe916c009ca1abfa524f1283db,
ZIP SHA256 e6f7885ad5b5736ce76bb58926172d3a3f93d47c9511012bc7abc48c204b1ebd.
The verifier compares actual ZIP bytes with immutable Git blobs, not working-tree files or README claims.
For a second independent method, download GitHub's source archive at that full commit,
and compare each `skills/aix` member to the corresponding ZIP member using the published hash map.
Do not repack the source archive and expect the same ZIP SHA: timestamps, ordering and metadata matter.

This is Git+hash provenance, not an independent digital signature. Frozen embedded checksum manifests
cover26 payload files; the external provenance map additionally covers all3 integrity metadata files,
so all29 ZIP members are included. No signing service or new infrastructure is introduced.

## Release state and scope

Source synchronization is not a formal release. No v0.2.3 tag, GitHub Release, website pointer update,
Beta deployment, Production change, identity operation or economic request is authorized by this source-only task.
The website's current0.2.2 package and older GitHub Releases are separate historical artifacts.
Do not advertise the candidate as installed from the public website until release authorization.

Only public Skill code, instructions, package tests and integrity metadata are mirrored.
No server code, deployment configuration, private keys, tokens, credentials, ledgers or real transactions are included.
Never overwrite identity state when installing/upgrading. Updates remain limited to package-owned files.

## Historical releases

Existing v0.1.0, v0.1.1, v0.2.0 and v0.2.1 GitHub Tags/Releases are preserved unchanged.
Their historical manifests and V0_2_0/V0_2_1 records describe those artifacts, not the0.2.3 candidate.
The latest GitHub Release is0.2.1; website0.2.2 has its own frozen package and original source snapshot
on the old PR4 branch. Closing that obsolete PR does not delete its branch or commit history.
No historical manifest is rewritten to claim a newer package hash.
