# Security and private material

Private vulnerability reporting is enabled for this public repository. Submit vulnerabilities privately through GitHub Security / Advisories by selecting **Report a vulnerability**. Do not post credentials, sensitive findings or restricted source text to a public issue. There is no announced contact address, response deadline or supported-release program. This repository setting is a private reporting channel, not a security guarantee supplied by the project code.

Do not run unknown documents simply because a checker accepts JSON. The mechanical checks are not a complete PDF security scanner, malware sandbox or security guarantee. They check scoped content/binding consistency. Source-authority declarations and JSON reviewer names do not authenticate identity or independence. Review only authorized input, in a private working directory.

Outputs use relative paths under an explicit root, reject reparse/link paths and avoid overwriting existing files. These controls are not protection against concurrent hostile filesystem replacement. Interrupted writes may leave a partial new file; investigate locally and use a new output name rather than treating the partial file as valid.

Share only reviewed counts/codes and an original neutral reproduction. Keep PDFs, input registries, extracted paragraphs, personal paths and detailed logs private. A local heuristic secrets scan cannot establish zero risk or validate a credential. No online credential validation is provided. See [input limits](docs/input_contract.md) and [contribution guidance](CONTRIBUTING.md).
