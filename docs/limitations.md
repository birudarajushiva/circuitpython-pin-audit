# Analysis contract and known limits

The analyzer walks module-level statements in order and maintains independent
symbolic name bindings and live pin claims for each explored path. A supported
constructor acquires claims; a direct `deinit()` or modeled `with` exit releases
them. Reassignment does not imply deinitialization. The analysis does not emulate
garbage collection or recover from runtime exceptions raised by constructors.

An unknown `if` condition forks the state. Its `else` is a separate path, so
resources allocated in opposite arms do not conflict with one another. Different
conditions are not correlated. For example, `if enabled:` followed by
`if not enabled:` may still produce a potential overlap. A path is a syntactic
possibility, not a proof of reachability. More than 64 concurrent paths is an
analysis failure (exit 2), not a clean report.

Function/class bodies and loop/try/match/async hardware operations are skipped.
Detected hardware references in these constructs generate PA101. Default-value
and decorator execution is not modeled. Imports inside skipped blocks are not
resolved. Star imports, expanded call arguments, implicit `board.I2C/SPI/UART`
pinouts, and unresolved pin expressions generate coverage warnings when detected.

Known mutating sequence methods, subscript assignment/deletion, and augmented
sequence assignment invalidate sequence aliases and produce coverage warnings.
Lists and tuples currently share a symbolic representation, so augmented tuple
assignment also invalidates aliases conservatively. Deleting a variable name
does not change other aliases. Python's complete alias/mutation semantics are
not implemented.
Passing a sequence through an arbitrary helper may mutate it without being
detected. A method alias such as `release = bus.deinit; release()` is not modeled
as a release. The same limitation applies to release inside an external helper.

Each input file starts with an empty state. Imported user modules are not loaded,
so cross-file allocations and pin constants can be missed. Each source file in a
directory is treated as a separate program, not an automatically discovered
module graph. Explicit files are recommended for CI.

Only listed constructor pin parameters are checked. Arbitrary external drivers
may acquire or release pins internally. A wrapper receiving a visible pin value
gets a warning, but wrappers receiving only configuration strings, or hiding
all their hardware setup internally, cannot be detected reliably. This means
coverage diagnostics describe known gaps, not a completeness certificate.

Names resolve symbolically: `board.D4` equals `board.D4`; a different spelling
equals it only when a user-supplied alias group says so. No board definition,
electrical connection, alternate-function routing, or actual pin capability is
assumed. `microcontroller.pin` objects and arbitrary `getattr` expressions are
currently unresolved.

The CLI parses source without executing it. That avoids firmware side effects;
it is not a hardened parser sandbox for arbitrarily hostile input. Source size
and path-count limits bound common accidental overloads, not all possible CPU,
memory, or filesystem races. Run scans with ordinary least-privilege file access.

Diagnostics:

- PA001: potentially live overlapping pin ownership.
- PA002: duplicate physical/symbolic pin within one constructor.
- PA100: unresolved/missing/implicit pin arguments.
- PA101: skipped or unmodeled hardware/lifetime code.
- PA900: unreadable or unparseable source.
- PA901: analysis resource limit.

Public APIs are `analyze(source, path, aliases=...)`, `Report`, and `Diagnostic`.
JSON schema 1 diagnostic positions are 1-based character positions. Ordering is
deterministic for identical inputs. Related positions identify the earlier
allocation; pin aliases are compared through a transitive equivalence relation.
