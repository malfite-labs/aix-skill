# Public Skill release memory

v0.2.0 mirrors allowlisted runtime/package files from Protocolmain9aac7788e4d9dd16828c995e8c50b8eba71d773c. Packagebuildskill-0.2.0-9aac7788e4d9 is immutable; V0_2_0_PROVENANCE.json records its digest and source. Runtime defaults to canonicalBeta only. No server, ledger, live credentials or private deployment records are mirrored.

Review/verification: protocol and Skill independently reviewed before deployment; public ZIP/perfile hashes and public Beta version checked, and dedicated Beta end-to-end smoke recorded separately in private protocol repository. Preserve exactArticleZero bytes and user instructions. Do not use genericPython HTTP headers to infer public outage: actual Skill UserAgent differs. Do not overwrite immutable releases or add separateBootstrap to0.9 onboarding.

Rule: release identity and sourceprovenance must match exact package bytes. Checklist: all runtime imports, consenthash, authenticatedhostscope, realbalance, optionalnativeauthorization, versionedURLs, digest verification. Anti-pattern: mirror whole private repository, copy credentials/tests into package, reset previousAgent balance, replace user config, mutate publishedZIP. Next optimization: keep release mirrors allowlisted and public verification use the real client.

## v0.2.1 P1 hotfix
Mirrors mergedProtocolmain4335bd388f884ddc236bd8fe173edc70e6525557, allowlisted packaged files only. CanonicalArticleZero1.0 bytes/hash unchanged. Creator reads real settledDelivery and authorizedfiles; honest_work requires no secondapproval and reading never settles again. Legacy contracts retained. Rule/checklist: validate actualreleaseZIP/filehashes, separate payment/quality/read/review; noledger/credential/privateproject data. Anti-pattern: publish unverifiedZIP orlabeldeliveryreading asmanualpaymentapproval. ScopepublicSkillonly; noProduction/Genesis changes.

## v0.2.1 P1 hotfix
Mirrors mergedProtocolmain4335bd388f884ddc236bd8fe173edc70e6525557, allowlisted packaged files only. CanonicalArticleZero1.0 bytes/hash unchanged. Creator reads real settledDelivery and authorizedfiles; honest_work requires no secondapproval and reading never settles again. Legacy contracts retained. Rule/checklist: validate actualreleaseZIP/filehashes, separate payment/quality/read/review; noledger/credential/privateproject data. Anti-pattern: publish unverifiedZIP orlabeldeliveryreading asmanualpaymentapproval. ScopepublicSkillonly; noProduction/Genesis changes.

## v0.2.2 source provenance and safety audit (2026-10-16)

The official website artifact is `skill-0.2.2-c00f9b937616`, ZIP SHA-256 `a3fc1dfdd1c95b2d91e435ef2d80909da33c055cc3ef697eb429ca6fffa031e0`. Protocol source is `malfite-labs/aix-protocol@c00f9b937616e0fc22c701fb78065065fc10544c`; public Skill source snapshot is `malfite-labs/aix-skill@d8e459d6e3fb74cb1a02308aeb01fbfeee4ccf77`. All 26 listed package-file hashes matched the fresh website ZIP and source snapshot. `V0_2_2_PROVENANCE.json` records the HTTPS artifact/descriptor hashes and mapping. No v0.2.2 GitHub Release/Tag or independent publisher signature existed at audit time. The immutable website package still embeds `public_source_repository: NOT_AVAILABLE_YET`; the repository record corrects discoverability without claiming the online ZIP was modified.

Delivery export creates a unique child directory and failure cleanup removes only that child. The destination parent and pre-existing files are preserved. `aix_installation.py` diagnostics are read-only; install guidance replaces package-owned files and does not remove unrelated Skill or user files. No network mutation, Beta/Production operation, ledger access, identity or credential action was performed.

Verification: scoped safety/provenance tests 3 passed. Full candidate repo tests: 354 passed, 6 failed, 3 skipped. The clean old-main baseline had 344 passed, 27 failed, 3 skipped; each of the six candidate failures also appears on baseline, so no new failure was observed. `git diff --check` passed before the documentation-only follow-up.

Rule: tie a published artifact to a public immutable source commit using actual package and per-file hashes; treat HTTPS SHA-256 plus a Git commit as integrity/provenance, not as a digital signature.
Checklist: download the public ZIP freshly; verify ZIP SHA; verify package file hashes against the source commit; inspect cleanup destinations; confirm install/update operations are limited to package-owned paths; test any credential store behavior only with an isolated temporary path.
Anti-pattern: edit an immutable public ZIP to fix metadata in place, claim a GitHub Release exists when only a website package is live, claim signed provenance when only checksums exist, or run storage tests against the default credential path.
