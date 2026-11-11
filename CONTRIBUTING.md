# Contributing

Start with a reproducible problem rather than a large rewrite. Good issues show
the smallest source file that demonstrates a false positive, missed conflict,
or unsupported constructor. Include the command, output, expected behavior,
board, and CircuitPython version. Link authoritative API documentation.

The project uses only the Python standard library at runtime. Keep that property
unless an issue establishes why a dependency is necessary. Run:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

New resource rules should have both a conflict test and a valid-use test. Changes
to lifetimes or control flow should include a negative case that prevents false
positives. Do not execute firmware, import user files, guess physical board
aliases, or silently label unsupported hardware code as analyzed.

Submit a focused pull request with the problem, resulting behavior, and checks
run. A supported constructor needs a reference in `docs/supported-api.md`. Runtime
or hardware verification must be labeled separately from static analysis.
