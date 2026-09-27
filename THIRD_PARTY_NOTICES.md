# Third-party dependency notices

SOURCE_ONLY_DEPENDENCY_LICENSE_SCOPE = PASS_WITH_SCOPE.

This repository distributes project source, rules/documentation, original examples/tests and the lock file. The following runtime dependencies are separately installed by the user. No third-party implementation, wheel, environment, runtime or installer is bundled. The project MIT License does not relicense these dependencies; each is provided under its own license.

| Dependency | Exact version | License expression | Official version source |
|---|---|---|---|
| pypdf | 6.19.0 | BSD-3-Clause | [PyPI](https://pypi.org/project/pypdf/6.19.0/) |
| jsonschema | 4.26.0 | MIT | [PyPI](https://pypi.org/project/jsonschema/4.26.0/) |
| attrs | 26.1.0 | MIT | [PyPI](https://pypi.org/project/attrs/26.1.0/) |
| jsonschema-specifications | 2025.9.1 | MIT | [PyPI](https://pypi.org/project/jsonschema-specifications/2025.9.1/) |
| referencing | 0.37.0 | MIT | [PyPI](https://pypi.org/project/referencing/0.37.0/) |
| rpds-py | 2026.6.3 | MIT | [PyPI](https://pypi.org/project/rpds-py/2026.6.3/) |
| typing-extensions | 4.16.0 | PSF-2.0 | [PyPI](https://pypi.org/project/typing-extensions/4.16.0/) |

This records the supplied exact-version official-source license review for the source-only distribution scope. It is not a third-party security audit, nor a claim that all upstream copyright or NOTICE texts were freshly read here. The historical PENDING_PUBLIC_RELEASE_REVIEW entries in [dependency provenance](docs/dependency_provenance.json) remain unchanged; the current source-only scope conclusion is stated above. Failure to re-download wheels is not a blocker for this scope.

Any future distribution of wheels, offline dependency bundles, installers, executables or copied third-party source requires a new distribution-license and NOTICE review. Preserve applicable upstream notices in that future distribution; do not replace their authorship with project attribution.
