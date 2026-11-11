# Supported constructor parameters

These are ownership checks for explicit board pins, not validation that a board
actually supports a peripheral or that the constructor call is otherwise valid.
Optional omitted or `None` pin parameters do not acquire a claim.

- [`busio`](https://docs.circuitpython.org/en/latest/shared-bindings/busio/index.html):
  `I2C(scl, sda)`, `SPI(clock, MOSI=None, MISO=None)`, and
  `UART(tx=None, rx=None, *, rts=None, cts=None, rs485_dir=None)`.
- [`bitbangio`](https://docs.circuitpython.org/en/latest/shared-bindings/bitbangio/index.html):
  `I2C(scl, sda)` and `SPI(clock, MOSI=None, MISO=None)`.
- [`digitalio`](https://docs.circuitpython.org/en/latest/shared-bindings/digitalio/index.html):
  `DigitalInOut(pin)`.
- [`analogio`](https://docs.circuitpython.org/en/latest/shared-bindings/analogio/index.html):
  `AnalogIn(pin)` and `AnalogOut(pin)`.
- [`pwmio`](https://docs.circuitpython.org/en/latest/shared-bindings/pwmio/index.html):
  `PWMOut(pin)`.
- [`rotaryio`](https://docs.circuitpython.org/en/latest/shared-bindings/rotaryio/index.html):
  `IncrementalEncoder(pin_a, pin_b)`.
- [`keypad`](https://docs.circuitpython.org/en/latest/shared-bindings/keypad/index.html):
  `Keys(pins)` and `KeyMatrix(row_pins, column_pins)`.

Both positional and named pin arguments are resolved. Non-pin options such as
baud rate, PWM frequency, debounce interval, or encoder divisor do not allocate
additional pins. Expanded arguments (`*args`, `**kwargs`) are not resolved.

These CircuitPython APIs document explicit `deinit()`/context-manager lifetimes.
Drivers accepting the same bus object do not themselves count as new bus
constructors. Library internals are not inspected.

The references above use upstream's latest documentation and can evolve. Add a
source reference and conflict/valid-use tests when updating a supported signature.
