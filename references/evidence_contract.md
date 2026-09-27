# Evidence bindings

Binding contract 2 hashes the complete validated project, including source/target/PDF references, pages, scope, layer declarations, vocabulary, term rules, pollution tokens, inspection and version. Source/target contract versions are included through their content hashes. Rule changes invalidate snapshot and cache bindings. The project and four schemas define required data. The source registry must say INDEPENDENT_SOURCE, identify the locked PDF and reject target-derived expectations. These declarations are checked for consistency, not authenticated as real observations.

Snapshot reports expose a digest without paths or text. `verify-snapshot` detects binding changes; `cache` also compares current script/schema bytes, and permits only binding reuse, never semantic-review reuse. `scope` requires changed and dependent units; it does not render pages. `route` distinguishes pending/open and bound rechecks. A resolved record and a required decision bind the same finding, scope and target. Target/scope changes invalidate the old record.

Only SYNTHETIC_TEST_ONLY records can exercise a successful offline coverage/decision-binding path. Such records are rejected in a non-synthetic project. No command creates genuine review or current human approval. Synthetic tests are not production events. Real independent review, human confirmation and release are separate unavailable states in this implementation.

Evidence references stay inside the explicit private run root. Shareable summaries contain digests, counts and error codes. Source and target context stays in private inputs; no diagnostic context-export option is supplied in this edition. An externally forged consistent set of JSON files is not proof of source authority or identity.
