# Security and private material

Private vulnerability reporting is **not configured**. A private channel and handling policy are publication prerequisites. There is no announced contact address, response deadline or supported-release program. Do not post credentials, sensitive findings or restricted source text to a public issue tracker. Until a private route is agreed, keep evidence local and ask for an authorized route without disclosing the sensitive content.

Do not run unknown documents simply because a checker accepts JSON. The mechanical checks are not a complete PDF security scanner, malware sandbox or security guarantee. They check scoped content/binding consistency. Source-authority declarations and JSON reviewer names do not authenticate identity or independence. Review only authorized input, in a private working directory.

Outputs use relative paths under an explicit root, reject reparse/link paths and avoid overwriting existing files. These controls are not protection against concurrent hostile filesystem replacement. Interrupted writes may leave a partial new file; investigate locally and use a new output name rather than treating the partial file as valid.

Share only reviewed counts/codes and an original neutral reproduction. Keep PDFs, input registries, extracted paragraphs, personal paths and detailed logs private. A local heuristic secrets scan cannot establish zero risk or validate a credential. No online credential validation is provided. See [input limits](docs/input_contract.md) and [contribution guidance](CONTRIBUTING.md).
