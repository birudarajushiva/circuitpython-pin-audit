# CircuitPython Pin Audit

**Find overlapping pin allocations before copying firmware to your board.**

A small static checker for CircuitPython setup code. It reads Python source,
tracks common hardware constructors, and points to both allocations when a pin
may still be owned. No CircuitPython installation, hardware, model API, or
runtime dependencies are needed. Firmware is never imported or executed.

This is an early, deliberately scoped tool. It reports potential conflicts and
coverage gaps; a clean report does not certify your circuit or firmware.

## A real reason to exist

In [HackPad's firmware](https://github.com/birudarajushiva/HackPad/blob/8ebea2cc15d34a8ab294d87b1208da995ef5eafb/firmware/main.py#L14),
the OLED bus claims D5 and D4, then a key matrix tries to claim those pins again.
Ordinary Python syntax checks cannot identify this hardware resource conflict.

The reduced reproduction in `examples/conflict.py` produces:

```text
examples/conflict.py:10:8: PA001 Potential overlap on board.D4: keypad.KeyMatrix (column_pins) and busio.I2C (sda, line 9).
examples/conflict.py:10:8: PA001 Potential overlap on board.D5: keypad.KeyMatrix (column_pins) and busio.I2C (scl, line 9).
```

## Try it in a minute

Use Python 3.10 or newer on your computer, not on the microcontroller:

```sh
git clone https://github.com/birudarajushiva/circuitpython-pin-audit.git
cd circuitpython-pin-audit
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
pin-audit examples/conflict.py
```

The last command intentionally exits **1** because the example has a conflict.
Then try valid shared-bus and released-pin examples:

```sh
pin-audit examples/shared_bus.py examples/released_pin.py
pin-audit /path/to/firmware/code.py
```

There is no PyPI release yet. Install from this repository or an attached wheel.
After installation, `python -m pin_audit` also works wherever the CLI is unavailable.

## What it understands

- Aliased imports and directly imported board pins or constructors.
- Constant pin assignments, tuples/lists, tuple concatenation, literal indexing,
  and unpacking.
- I²C, SPI, UART (including flow-control pins), digital I/O, analog I/O, PWM,
  rotary encoders, independent keys, and key matrices.
- Explicit `resource.deinit()` and supported resources used as context managers.
- Separate `if`/`else` paths, literal constant conditions, and terminated `raise`
  paths. Reports are deduplicated across explored paths.
- Multiple drivers sharing the **same** I²C/SPI object, which does not allocate
  another set of bus pins.

For constructor details and authoritative references, see
[supported APIs](docs/supported-api.md).

## Board pin aliases

`board.SDA` and `board.D4` may name the same pad on one board and different pads
on another. The checker does not guess. Supply groups verified against your
board's definition:

```json
{"aliases": [["D4", "SDA"], ["D5", "SCL"]]}
```

Save that as `board-aliases.json` and run:

```sh
pin-audit code.py --aliases board-aliases.json
```

Those groups are an example, not a universal board pinout. Groups can overlap;
alias equivalence is transitive. Names are board attributes without the `board.` prefix.

## CI and editor integration

```sh
pin-audit firmware/ --exclude 'vendor/*' --format github
pin-audit code.py --format json > pin-report.json
pin-audit code.py --strict
```

Exit codes:

- **0:** no potential conflict found in analyzed code. Coverage warnings can
  still be present; this is not proof of correctness.
- **1:** potential overlap/duplicate pin, or a coverage warning with `--strict`.
- **2:** invalid input, unreadable/unparseable source, or an analysis limit.

JSON has `schema_version: 1`, per-file allocation counts, diagnostics, pin names,
and related source positions. `--format github` emits escaped workflow
annotations. `--strict` makes unsupported/dynamic hardware setup fail CI rather
than silently treating it as checked.

Directories are scanned recursively for `.py` files. Each file is analyzed as an
**independent entrypoint**; resources in separate files are not combined.
Duplicate input paths are deduplicated. Common environment/build folders and
symlinks are skipped during discovery; explicitly supplied symlinks are rejected.
Files are limited to 2 MiB. Prefer scanning your entrypoint explicitly when the
directory also contains libraries or alternative examples.

To add a GitHub Actions step, install a reviewed commit of this tool and run
`pin-audit code.py --format github`. See the
[integration guide](docs/integration.md) for a complete workflow and safe adoption
when existing firmware already has findings.

## Boundaries you should know

This is a single-file symbolic analysis, not a full Python interpreter or a
CircuitPython simulator. It does not model inter-file imports, helper-function
calls, class bodies, loop/try/match hardware operations, implicit bus pinouts,
arbitrary driver internals, or arbitrary Python mutation. Recognized skipped
hardware constructs generate coverage warnings, but the analyzer cannot
identify every unrecognized wrapper. See [analysis limits](docs/limitations.md).

Unknown conditions are explored independently; correlations between separate
conditions are not solved. An overlap is therefore a **potential** conflict,
not proof the path will execute. Hardware resources hidden inside external
drivers can be missed. Rebinding/deleting a Python variable is not treated as
release; use explicit `deinit()` or a modeled context manager.

It also does not check board pin availability, peripheral multiplexing,
voltage/current, wiring, physical assembly, or CircuitPython-version compatibility.

## Develop and contribute

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests include the HackPad pin-conflict regression, valid shared buses, resource
release, branch separation, explicit aliases, unsafe-code non-execution, CLI
exit codes, encoding handling, and annotation escaping.

Useful contributions start with a **minimal reproducer**: a missed conflict, a
false positive, or an official constructor signature we do not support. Include
the board/CircuitPython version, expected result, and a reference to the API.
Remove credentials and private application code. See [CONTRIBUTING.md](CONTRIBUTING.md).

MIT licensed. Not affiliated with or endorsed by Adafruit or CircuitPython.
