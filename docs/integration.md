# Integrate with an existing project

First run the checker locally against your actual firmware entrypoint. Resolve
PA001/PA002 before making it a required CI check. Coverage warnings identify
known gaps; `--strict` also fails on them. Review the documented analysis limits
before deciding whether strict mode suits your setup.

## GitHub Actions

Replace `REVIEWED_COMMIT_SHA` below with a full commit you reviewed from this
repository, rather than automatically executing the newest tool revision.

```yaml
name: Pin audit
on: [push, pull_request]
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: '3.12'
      - run: python -m pip install 'git+https://github.com/birudarajushiva/circuitpython-pin-audit.git@REVIEWED_COMMIT_SHA'
      - run: pin-audit firmware/code.py --format github --strict
```

Paths in annotations are the input source paths. Use repository-relative paths
for GitHub to associate diagnostics with files. The workflow needs no API key,
board connection, additional token permission, or CircuitPython dependency.

## pre-commit

```yaml
repos:
  - repo: https://github.com/birudarajushiva/circuitpython-pin-audit
    rev: REVIEWED_COMMIT_SHA
    hooks:
      - id: pin-audit
        files: ^firmware/code\.py$
        args: [--strict]
```

Each passed file is an independent entrypoint. Do not assume scanning a directory
combines pin ownership across imported modules.

## Existing findings

The tool does not silently suppress a baseline of known pin conflicts. If your
firmware already reports a conflict, keep the initial integration advisory until
you verify a fix against the schematic and board. Do not randomly pick an unused
symbolic pin: the PCB may require a hardware revision too.

For the motivating [HackPad case](https://github.com/birudarajushiva/HackPad),
D4/D5 are claimed by the I²C OLED bus and key matrix. The checker establishes the
source-level overlap; it does not determine a physically correct replacement.
