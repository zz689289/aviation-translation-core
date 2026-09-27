# QA and human confirmation

Mechanical consistency, semantic review, human confirmation and release are distinct. Inspect omission/addition, condition, negation, normative strength, identifiers, quantities, units, symbols, terminology and each supported content layer. Independently account for all source units, including absent-layer evidence. Missing extraction is not absence.

Simple text PDF extraction cannot establish graphical or semantic completeness. This implementation rejects encrypted/active PDFs, annotations/XObjects on selected pages, failed extraction and text mapping differences. Other unrecognized PDF constructs and declared absence still require independent visual/source QA. Do not use it as a complete PDF security inspector.

The default final state is BLOCKED_PENDING_REAL_QA even after all mechanical checks pass. Unsupported layers, pending translation or missing evidence block their gates. Actual source-first independent QA and a current human decision must occur outside this offline candidate before any complete review or release claim. Never rebrand test PASS as translation quality or public readiness.
