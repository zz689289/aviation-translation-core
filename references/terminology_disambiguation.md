# Contextual terminology

Match phrases with their context and technical function. Do not globally replace ambiguous words or invent abbreviation expansions. This candidate ships no inherited institutional glossary. Rules in each private input contain explicit forms, case behavior and controlled required/forbidden target strings.

`term_guard.py` matches each rule independently with word boundaries. Forms within a rule are ordered by length; different rules can overlap and each occurrence is counted. This is not a tokenizer, automatic disambiguator or correction engine. It does not infer inflections: supply forms explicitly. A required target match is a mechanical string condition, not proof of approved terminology or equivalent meaning.

Keep rule approval in real project decisions. Unknown official expressions or a change in technical meaning require actual reviewer/human disposition. Shared output contains no matched paragraphs; authorized reviewers consult the private source/target inputs.
