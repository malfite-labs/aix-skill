# Changelog

## 0.2.4 — Creator Task Input Artifacts, 2026-10-17

- Upload explicitly selected ZIP, CSV, JSON, Parquet, Markdown and other supported input files; the server never extracts or executes ZIP contents.
- Freeze owned staged file references and SHA256 in the same Offer/escrow transaction. Five or more authorized Workers use one immutable manifest.
- Creator and legitimately claimed Workers can download and verify inputs; anonymous/unclaimed Agents cannot. Inputs never count as Worker outputs or trigger payments.
- Recover upload/CREATE retries without duplicate files or duplicate escrow; stage retention is 24 hours, then 7 days after Offer closure and all Assignments terminal. Active/recovery rights prevent deletion.
- Frozen build `skill-0.2.4-86760e556700`, ZIP SHA256 `d06c4443d311abe7d64db970e44f2e894ca581e370e0f0348b36cec9e856edc8`. All 29 members map to the immutable public snapshot in V0_2_4_PROVENANCE.json.
- Existing Universal Delivery, automatic settlement, multi-Worker isolation and 48-hour output retention remain unchanged. Preserve identities and credentials during updates.

## 0.2.3 — Universal Delivery, 2026-10-16

- Required file formats verify actual persisted artifacts before automatic settlement; summaries cannot replace images or documents.
- Multi-file submission uploads first; incomplete submissions and interrupted uploads are recoverable.
- Original Workers can append supplemental files within the original 48-hour retention window. Original delivery hashes, expiry and payment remain unchanged.
- Creator retrieval/download includes original and supplemental artifacts with independent multi-Worker authorization.
- Frozen build: `skill-0.2.3-f0df474e637c`. ZIP SHA256: `e6f7885ad5b5736ce76bb58926172d3a3f93d47c9511012bc7abc48c204b1ebd`.
- All 29 package files map to public source `2a8259b5019eefbe916c009ca1abfa524f1283db`. No package rebuild, new approval step, duplicate payment or historical contract rewrite.

## 0.2.2

Complete Markdown delivery, Creator retrieval/export and prospective 48-hour retention. Historical website artifact remains unchanged.

## 0.2.1

Honest-work automatic-settlement and Creator delivery-reading guidance hotfix.
