# Windows quickstart

This public pre-release source repository runs offline after dependencies are present. It does not translate text or approve publication. Use a Git checkout or downloaded source archive; no Git expertise or Skill installation is required to run the existing offline demo. No tagged release or support promise is provided.

## 1. Locate inputs and choose private work

The recorded environment is Windows with CPython 3.12.14, pypdf 6.19.0 and jsonschema 4.26.0. All seven dependencies are pinned in [requirements.lock](../requirements.lock); hashes refer to specific artifacts listed in [dependency provenance](dependency_provenance.json). This is not a portable lock for arbitrary Python, OS or architecture. Linux supplemental execution does not establish Linux installation support. Stop on an unavailable artifact; do not bypass hashes or change pins to make installation succeed.

In PowerShell, replace only the two placeholders with paths you actually have. Check literal paths before running commands. Do not install Python globally or change system configuration for this guide.

```powershell
$ErrorActionPreference = 'Stop'
$candidate = '<absolute path to the candidate folder>'
$python = '<absolute path to an existing compatible Python executable>'
if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { throw 'Candidate missing' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python missing' }
$candidate = (Resolve-Path -LiteralPath $candidate).Path
Set-Location -LiteralPath $candidate
foreach ($relative in @('requirements.lock','examples/run_demo.py','tests/run_tests.py','scripts/compare_source.py','scripts/term_guard.py','scripts/check_invariants.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $candidate $relative) -PathType Leaf)) { throw 'Required candidate file missing' }
}
$runParent = Join-Path $candidate 'private_run'
# You may instead select an explicit private output directory outside the candidate.
if (Test-Path -LiteralPath $runParent) {
    if (-not (Test-Path -LiteralPath $runParent -PathType Container)) { throw 'Work parent is not a directory' }
} else { New-Item -ItemType Directory -Path $runParent -ErrorAction Stop | Out-Null }
$run = Join-Path $runParent ('run_' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $run) { throw 'Run already exists' }
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
$env:TEMP = $run
$env:TMP = $run
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
# Process-only isolation used in the accepted installation verification.
$env:PIP_CONFIG_FILE = 'NUL'
& $python -X utf8 -I -B --version
if ($LASTEXITCODE -ne 0) { throw 'Python version query failed' }
```

Confirm the displayed interpreter version against the supported environment. Keep all generated data in this fresh run. Do not rerun a block against used output names.

## 2. Isolate and install (validated in accepted installation evidence)

The accepted installation verification used CPython 3.12.14 / Windows x64 and a newly created venv on the same computer. Seven locked dependencies matched versions, wheel hashes and new-environment import locations; pip check passed. Installation uses the standard public package index. This is not certification of a new computer or arbitrary platforms. No installation was rerun during the license documentation update. Do not run these commands against an existing environment.

```powershell
$venv = Join-Path $run '.venv'
if (Test-Path -LiteralPath $venv) { throw 'Environment already exists' }
& $python -X utf8 -I -B -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
$py = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw 'Environment Python missing' }
& $py -X utf8 -I -B -m pip --isolated --disable-pip-version-check install --no-cache-dir --index-url https://pypi.org/simple --require-hashes -r (Join-Path $candidate 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed' }
```

If an isolated compatible environment with the exact locked dependencies already exists, skip both installation commands and set `$py` to its executable. Verify the file with `Test-Path -LiteralPath $py -PathType Leaf`; use it read-only. That route was used in the earlier documentation verification; the subsequent accepted installation verification used a fresh venv instead. PIP_CONFIG_FILE=NUL applies only to the current process and its children, disabling pip configuration-file loading without modifying system/user configuration files. Do not upgrade the existing environment. `$run` must still be a new private directory prepared above.

## 3. Run the demo and existing tests

Run this block once after `$candidate`, `$py` and the new `$run` are prepared. All native commands explicitly check `$LASTEXITCODE`; stop rather than interpreting partial files as successful output.

```powershell
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw 'Interpreter missing' }
Set-Location -LiteralPath $candidate
$demo = Join-Path $run 'demo'
if (Test-Path -LiteralPath $demo) { throw 'Demo output already exists' }
New-Item -ItemType Directory -Path $demo -ErrorAction Stop | Out-Null
& $py -X utf8 -I -B examples/run_demo.py --output $demo
if ($LASTEXITCODE -ne 0) { throw 'Demo failed; stop and inspect private output.' }
$testsWork = Join-Path $run 'tests'
$results = Join-Path $run 'tests.json'
$log = Join-Path $run 'tests.private.log'
foreach ($path in @($testsWork,$results,$log)) {
    if (Test-Path -LiteralPath $path) { throw 'Test output already exists' }
}
& $py -X utf8 -I -B tests/run_tests.py --work $testsWork --results $results *> $log
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; inspect private results and stop.' }
Get-Content -LiteralPath $results
```

The demo generates original English/Chinese registries and a small text PDF, plus terms.summary.json, source_location.summary.json, invariants.summary.json and handoff.summary.json. No API, OCR, external font or translation service is used. Keep generated PDFs, registries and detailed logs private.

A summary can simultaneously report `mechanical_status=PASS`, `completion=BLOCKED_PENDING_REAL_QA`, `human_approved=false`, `released=false`. This is intentional: a mechanical result does not establish translation quality, independent semantic review or permission to publish. Workflow outputs also keep trusted host integration NOT_RUN. A snapshot alone does not run all term/invariant checks.

The accepted fresh-venv installation run passed the Demo and all three individual entries. Of 99 tests, 98 passed with zero failures and the file-symlink case was NOT_TESTED on the restricted Windows account. These are cited installation results, not tests rerun for the license update. Do not elevate permissions or turn a skip into PASS. A zero test-process exit can include skipped cases: inspect the counts and reasons.

## 4. Individual mechanical entries

The demo inputs can also be used for these real entry points. Use new output names, never an input filename. Each check has a separate result; this is not a combined translation approval.

```powershell
& $py -X utf8 -I -B scripts/compare_source.py --root $demo --spec project.json --output additional-source.json
if ($LASTEXITCODE -ne 0) { throw 'Source check did not pass' }
& $py -X utf8 -I -B scripts/term_guard.py --root $demo --spec project.json --output additional-terms.json
if ($LASTEXITCODE -ne 0) { throw 'Term check did not pass' }
& $py -X utf8 -I -B scripts/check_invariants.py --root $demo --spec project.json --output additional-invariants.json
if ($LASTEXITCODE -ne 0) { throw 'Invariant check did not pass' }
```

Exit 0 indicates that command's mechanical pass; exit 1 indicates reported check failures; exit 2 indicates invalid inputs or a blocked operation. Keep error codes; do not share private context to explain them publicly. Default writes do not overwrite. For real inputs, read [manual preparation](preparing_inputs.md), [contract limits](input_contract.md) and [QA policy](../references/qa_policy.md). There is no automatic import pipeline. Software use and redistribution are governed by the root [LICENSE](../LICENSE). Running these checks does not authorize publication of a translation or establish independent semantic QA.
