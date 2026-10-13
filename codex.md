# Public Skill release memory

v0.2.0 mirrors allowlisted runtime/package files from Protocolmain9aac7788e4d9dd16828c995e8c50b8eba71d773c. Packagebuildskill-0.2.0-9aac7788e4d9 is immutable; V0_2_0_PROVENANCE.json records its digest and source. Runtime defaults to canonicalBeta only. No server, ledger, live credentials or private deployment records are mirrored.

Review/verification: protocol and Skill independently reviewed before deployment; public ZIP/perfile hashes and public Beta version checked, and dedicated Beta end-to-end smoke recorded separately in private protocol repository. Preserve exactArticleZero bytes and user instructions. Do not use genericPython HTTP headers to infer public outage: actual Skill UserAgent differs. Do not overwrite immutable releases or add separateBootstrap to0.9 onboarding.

Rule: release identity and sourceprovenance must match exact package bytes. Checklist: all runtime imports, consenthash, authenticatedhostscope, realbalance, optionalnativeauthorization, versionedURLs, digest verification. Anti-pattern: mirror whole private repository, copy credentials/tests into package, reset previousAgent balance, replace user config, mutate publishedZIP. Next optimization: keep release mirrors allowlisted and public verification use the real client.
