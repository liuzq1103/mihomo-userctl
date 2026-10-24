# v1.4.1 independent review record

The implementation follows the MiniMax-M3.1-Flash design review: preserve the complete offline application, prune explicit duplicate/development runtime files, retain the link-free format, keep legacy migration tests, and add a separate real v1.4.0 portable upgrade.

GPT-6-Astra reviewed runtime pruning, dependency coverage, live-core upgrade identity, filesystem measurements and portable acceptance. Its two blocking findings were corrected: the controller configuration reader returns three values, and ELF checks must include application/dependency extensions as well as CPython. A follow-up review confirmed both fixes and found no further static blocker. Initialization sampling and external storage are reported separately from per-home installer/update observations.

GPT-6-Sol reviewed CI provenance, candidate selection, resumable drafts, tag identity and public acquisition. Findings resolved before publication: verify the baseline before any release action; compare secondary portable checksums; validate draft title/notes and reread edits; refuse public asset/note repairs; require the public tag to exist and peel to the validated commit. Follow-up review found no further publication blocker. Unit tests cover these failure boundaries.

The secondary environment's receipt must match its own installed artifact report. Source archive identities and portable bytes match across targets; universal wheel ZIP metadata is allowed to differ, preserving the existing compatibility contract. Each asset selected for publication must have corresponding installation evidence.

These are code/design reviews, not substitutes for executed acceptance. The final main commit must pass the complete two-Ubuntu release gate, including real UIDs, SSH/PTY, network isolation, v1.0.x migration and live-core v1.4.0 upgrades. The publisher binds the release to that successful run, verifies draft downloads, and records public download/fetch/update smoke evidence after publication.
