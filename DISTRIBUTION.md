# Distribution and provenance

The official Skill v0.2.2 package is currently served from https://skill.aixprotocol.org/releases/skill-0.2.2-c00f9b937616/AIX-Skill-v0.1.zip. Its observed SHA-256 is `a3fc1dfdd1c95b2d91e435ef2d80909da33c055cc3ef697eb429ca6fffa031e0`.

The GitHub repository is the public source repository. The v0.2.2 source snapshot and its per-file comparison against the frozen package are recorded in `V0_2_2_PROVENANCE.json`. This record identifies the exact public source commit and the upstream AIX Protocol commit used by the build. The package's embedded `public_source_repository: NOT_AVAILABLE_YET` value is stale; the provenance record is the corrective repository-level metadata.

There is no GitHub v0.2.2 Release or tag yet. The existing immutable releases v0.2.1 and earlier remain historical. The v0.2.2 source commit is independently inspectable in this repository; publishing a GitHub Release is a separate release action.

Updates replace package-owned Skill files only and must preserve Agent identity and credential storage. Diagnostic helpers are read-only. Delivery export failures remove only the newly created private export directory, never the caller's destination directory.
