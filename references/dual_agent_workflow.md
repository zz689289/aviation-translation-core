# Independent QA handoff

An executor prepares a stable snapshot of the original, target, mapping, checker and scope. A genuinely separate host agent first inventories the original source, then checks the translation; do not seed its first review with executor PASS claims. Reconcile source coverage only after its source-first review. The reviewer writes evidence, never production artifacts or automatic approvals.

Use current hashes and source/target scope bindings for handoff and follow-up. Review affected scope and dependent units after repairs. Preserve the distinction between unfinished work, a source-clear repair and a technical decision. Human confirmation attaches to the current target and scope.

This candidate does not dispatch agents or authenticate events. Real host integration is NOT_RUN. Without a separately verified host event source, state INDEPENDENT_QA_UNAVAILABLE. `coverage` can test synthetic record consistency, but outputs always retain unavailable real QA and false human/release flags. Do not change those flags by creating JSON records. A future trusted host adapter needs its own authorized integration test and real event provenance.
