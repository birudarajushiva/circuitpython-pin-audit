"""A bounded, single-file symbolic pass over common CircuitPython constructors.

This is intentionally not an interpreter. Unknown Python stays unknown, board
aliases are explicit, and skipped constructs produce coverage diagnostics.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


# Pin parameters only. Later positional arguments (e.g. baudrate) are not pins.
# None is an optional, unconnected pin. See docs/supported-api.md for sources.
SPECS: dict[str, tuple[str, ...]] = {
    "busio.I2C": ("scl", "sda"),
    "bitbangio.I2C": ("scl", "sda"),
    "busio.SPI": ("clock", "MOSI", "MISO"),
    "bitbangio.SPI": ("clock", "MOSI", "MISO"),
    "busio.UART": ("tx", "rx"),
    "digitalio.DigitalInOut": ("pin",),
    "analogio.AnalogIn": ("pin",),
    "analogio.AnalogOut": ("pin",),
    "pwmio.PWMOut": ("pin",),
    "rotaryio.IncrementalEncoder": ("pin_a", "pin_b"),
    "keypad.Keys": ("pins",),
    "keypad.KeyMatrix": ("row_pins", "column_pins"),
}
EXTRA_PINS = {"busio.UART": ("rts", "cts", "rs485_dir")}
REQUIRED = {
    name: len(params) for name, params in SPECS.items()
    if name not in {"busio.SPI", "bitbangio.SPI", "busio.UART"}
}
REQUIRED.update({"busio.SPI": 1, "bitbangio.SPI": 1, "busio.UART": 0})
MODULES = {name.split(".")[0] for name in SPECS} | {"board"}
UNKNOWN = object()
SKIPPED_BLOCKS = (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.AsyncWith, ast.Match)
if hasattr(ast, "TryStar"):
    SKIPPED_BLOCKS += (ast.TryStar,)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    line: int
    column: int
    message: str
    pin: str | None = None
    related_line: int | None = None
    related_column: int | None = None


@dataclass
class Report:
    path: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    allocations: int = 0

    @property
    def conflicts(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.code in {"PA001", "PA002"}]

    @property
    def incomplete(self) -> bool:
        return any(d.code.startswith("PA1") for d in self.diagnostics)

    @property
    def failed(self) -> bool:
        return any(d.code.startswith("PA9") for d in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "allocations": self.allocations,
            "conflicts": len(self.conflicts),
            "incomplete": self.incomplete,
            "failed": self.failed,
            "diagnostics": [asdict(d) for d in self.diagnostics],
        }


@dataclass(frozen=True)
class Symbol:
    name: str


@dataclass(frozen=True)
class Pin:
    name: str


@dataclass(frozen=True)
class Handle:
    key: tuple[int, int]


@dataclass(frozen=True)
class Claim:
    pin: str
    spelling: str
    constructor: str
    role: str
    line: int
    column: int


@dataclass
class State:
    names: dict[str, Any] = field(default_factory=dict)
    live: dict[tuple[int, int], list[Claim]] = field(default_factory=dict)

    def copy(self) -> State:
        # All symbolic values and claim lists are immutable after insertion.
        return State(dict(self.names), dict(self.live))


class Analyzer:
    def __init__(self, path: str, aliases: Iterable[Iterable[str]], max_paths: int, source: str):
        self.report = Report(path)
        self.lines = source.splitlines()
        self.parent: dict[str, str] = {}
        self.max_paths = max_paths
        self.seen: set[Diagnostic] = set()
        self.allocations: set[tuple[int, int]] = set()
        for group in aliases:
            names = list(group)
            for name in names[1:]:
                source_root, target_root = self.canonical(name), self.canonical(names[0])
                if source_root != target_root:
                    self.parent[source_root] = target_root

    def canonical(self, pin: str) -> str:
        while pin in self.parent:
            pin = self.parent[pin]
        return pin

    def emit(self, code: str, node: ast.AST, message: str, **kwargs: Any) -> None:
        severity = "error" if code in {"PA001", "PA002"} or code.startswith("PA9") else "warning"
        item = Diagnostic(code, severity, getattr(node, "lineno", 1),
                          self.column(node), message, **kwargs)
        if item not in self.seen:
            self.report.diagnostics.append(item)
            self.seen.add(item)

    def column(self, node: ast.AST) -> int:
        line = getattr(node, "lineno", 1)
        offset = getattr(node, "col_offset", 0)
        if 1 <= line <= len(self.lines):
            return len(self.lines[line - 1].encode("utf-8")[:offset].decode("utf-8", errors="replace")) + 1
        return offset + 1

    def qualify(self, node: ast.AST, state: State) -> str | None:
        if isinstance(node, ast.Name):
            value = state.names.get(node.id)
            return value.name if isinstance(value, Symbol) else None
        if isinstance(node, ast.Attribute):
            base = self.qualify(node.value, state)
            return f"{base}.{node.attr}" if base else None
        return None

    def relevant(self, node: ast.AST, state: State) -> bool:
        """Does a skipped construct contain potential hardware/lifetime code?"""
        for child in ast.walk(node):
            if isinstance(child, ast.Import) and any(a.name in MODULES for a in child.names):
                return True
            if isinstance(child, ast.ImportFrom) and child.module in MODULES:
                return True
            if isinstance(child, ast.Call):
                name = self.qualify(child.func, state)
                if name in SPECS or name in {"board.I2C", "board.SPI", "board.UART"}:
                    return True
                if isinstance(child.func, ast.Attribute) and child.func.attr == "deinit":
                    return True
            if isinstance(child, ast.Attribute) and self.qualify(child.value, state) == "board":
                return True
        return False

    def flatten(self, value: Any) -> list[Pin] | None:
        if isinstance(value, Pin):
            return [value]
        if isinstance(value, tuple):
            result: list[Pin] = []
            for entry in value:
                pins = self.flatten(entry)
                if pins is None:
                    return None
                result.extend(pins)
            return result
        if value is None:
            return []
        return None

    def allocate(self, node: ast.Call, name: str, args: list[Any],
                 keywords: dict[str, Any], state: State) -> Handle:
        self.allocations.add((node.lineno, node.col_offset))
        claims: list[Claim] = []
        if any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
            self.emit("PA100", node, f"{name}: expanded arguments cannot be resolved; allocation skipped.")
            return Handle((node.lineno, node.col_offset))
        params = SPECS[name]
        fields = {param: args[i] for i, param in enumerate(params) if i < len(args)}
        fields.update({k: v for k, v in keywords.items() if k in (*params, *EXTRA_PINS.get(name, ()))})
        for i, param in enumerate(params[:REQUIRED[name]]):
            if param not in fields:
                self.emit("PA100", node, f"{name}: required pin argument {param!r} is missing.")
        for role, value in fields.items():
            pins = self.flatten(value)
            if pins is None:
                self.emit("PA100", node, f"{name}: cannot resolve pin argument {role!r} statically.")
                continue
            if not pins and role in params[:REQUIRED[name]]:
                self.emit("PA100", node, f"{name}: required pin argument {role!r} has no resolved pins.")
            for pin in pins:
                claim = Claim(self.canonical(pin.name), pin.name, name, role,
                              node.lineno, self.column(node))
                duplicate = next((c for c in claims if c.pin == claim.pin), None)
                if duplicate:
                    self.emit("PA002", node,
                              f"board.{pin.name} is used twice by {name} ({duplicate.role}, {role}).",
                              pin=claim.pin)
                for previous in (c for group in state.live.values() for c in group):
                    if previous.pin == claim.pin:
                        self.emit("PA001", node,
                                  f"Potential overlap on board.{pin.name}: {name} ({role}) and "
                                  f"{previous.constructor} ({previous.role}, line {previous.line}).",
                                  pin=claim.pin, related_line=previous.line,
                                  related_column=previous.column)
                claims.append(claim)
        handle = Handle((node.lineno, node.col_offset))
        state.live[handle.key] = claims
        return handle

    def value(self, node: ast.AST | None, state: State) -> Any:
        if node is None:
            return UNKNOWN
        if isinstance(node, ast.Name):
            return state.names.get(node.id, UNKNOWN)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(self.value(item, state) for item in node.elts)
        if isinstance(node, ast.Attribute):
            if self.qualify(node.value, state) == "board":
                return Pin(node.attr)
            qualified = self.qualify(node, state)
            return Symbol(qualified) if qualified else UNKNOWN
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.value(node.left, state), self.value(node.right, state)
            return left + right if isinstance(left, tuple) and isinstance(right, tuple) else UNKNOWN
        if isinstance(node, ast.Subscript):
            seq, index = self.value(node.value, state), self.value(node.slice, state)
            if isinstance(seq, tuple) and type(index) is int and -len(seq) <= index < len(seq):
                return seq[index]
            return UNKNOWN
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "deinit":
                owner = self.value(node.func.value, state)
                if isinstance(owner, Handle) and not node.args and not node.keywords:
                    state.live.pop(owner.key, None)
                else:
                    self.emit("PA101", node, "Cannot resolve this deinit() receiver or call signature.")
                return UNKNOWN
            name = self.qualify(node.func, state)
            args = [self.value(arg, state) for arg in node.args]
            keywords = {k.arg: self.value(k.value, state) for k in node.keywords}
            if name in SPECS:
                return self.allocate(node, name, args, keywords, state)
            if name in {"board.I2C", "board.SPI", "board.UART"}:
                self.emit("PA100", node, f"{name}() uses board-specific default pins; use an explicit bus constructor to audit them.")
            elif any(self.flatten(v) for v in [*args, *keywords.values()]):
                self.emit("PA101", node, "Unmodeled call receives pin values; its ownership behavior is not analyzed.")
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                target = node.func.value.id
                if isinstance(state.names.get(target), tuple) and node.func.attr in {
                    "append", "extend", "insert", "pop", "clear", "remove", "reverse", "sort"
                }:
                    previous = state.names[target]
                    for alias in list(state.names):
                        if state.names[alias] is previous:
                            state.names[alias] = UNKNOWN
                    self.emit("PA101", node, "Mutated pin sequence is no longer statically resolved.")
            return UNKNOWN
        # Do not descend into comprehensions, lambdas, or conditional expressions:
        # their execution order is not the same as an unconditional AST walk.
        if any(isinstance(child, ast.Call) for child in ast.walk(node)) and self.relevant(node, state):
            self.emit("PA101", node, "Hardware calls inside this expression are not analyzed.")
        return UNKNOWN

    def bind(self, target: ast.AST, value: Any, state: State) -> None:
        if isinstance(target, ast.Name):
            state.names[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            values = value if isinstance(value, tuple) and len(value) == len(target.elts) else (UNKNOWN,) * len(target.elts)
            for entry, item in zip(target.elts, values):
                self.bind(entry, item, state)
        elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
            previous = state.names.get(target.value.id)
            for alias in list(state.names):
                if state.names[alias] is previous:
                    state.names[alias] = UNKNOWN
            self.emit("PA101", target, "Sequence assignment is not statically resolved.")

    def block(self, nodes: list[ast.stmt], states: list[State]) -> list[State]:
        for node in nodes:
            next_states: list[State] = []
            for state in states:
                next_states.extend(self.statement(node, state))
                if len(next_states) > self.max_paths:
                    self.emit("PA901", node, f"Analysis stopped: more than {self.max_paths} control-flow paths.")
                    return []
            states = next_states
            if not states:
                break
        return states

    def statement(self, node: ast.stmt, state: State) -> list[State]:
        if isinstance(node, ast.Import):
            for alias in node.names:
                state.names[alias.asname or alias.name.split(".")[0]] = Symbol(alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    self.emit("PA101", node, "Wildcard import is not resolved; use explicit imports.")
                elif node.module == "board":
                    state.names[alias.asname or alias.name] = (
                        Symbol(f"board.{alias.name}") if alias.name in {"I2C", "SPI", "UART"} else Pin(alias.name)
                    )
                else:
                    state.names[alias.asname or alias.name] = Symbol(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Assign):
            result = self.value(node.value, state)
            for target in node.targets:
                self.bind(target, result, state)
        elif isinstance(node, ast.AnnAssign):
            self.bind(node.target, self.value(node.value, state), state)
        elif isinstance(node, ast.AugAssign):
            self.bind(node.target, UNKNOWN, state)
        elif isinstance(node, ast.Expr):
            self.value(node.value, state)
        elif isinstance(node, ast.If):
            self.value(node.test, state)
            if isinstance(node.test, ast.Constant):
                return self.block(node.body if node.test.value else node.orelse, [state])
            return self.block(node.body, [state.copy()]) + self.block(node.orelse, [state.copy()])
        elif isinstance(node, ast.With):
            handles: list[Handle] = []
            for item in node.items:
                result = self.value(item.context_expr, state)
                if isinstance(result, Handle):
                    handles.append(result)
                if item.optional_vars:
                    self.bind(item.optional_vars, result, state)
            states = self.block(node.body, [state])
            for branch in states:
                for handle in handles:
                    branch.live.pop(handle.key, None)
            return states
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # A definition is not a call. Do not count allocations inside it.
            if self.relevant(node, state):
                self.emit("PA101", node, "Function/class bodies are not analyzed; move auditable allocation to module-level setup.")
            state.names[node.name] = UNKNOWN
        elif isinstance(node, ast.Raise):
            self.value(node.exc, state)
            return []
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    state.names.pop(target.id, None)
        elif isinstance(node, SKIPPED_BLOCKS):
            if self.relevant(node, state):
                self.emit("PA101", node, "Loop/try/match/async hardware operations are not analyzed.")
            # Do not keep stale constant aliases after skipped assignments/imports.
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    state.names[child.id] = UNKNOWN
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        state.names[alias.asname or alias.name.split(".")[0]] = UNKNOWN
        elif self.relevant(node, state):
            self.emit("PA101", node, "Hardware operations in this statement are not analyzed.")
        return [state]


def analyze(source: str, path: str = "code.py", *,
            aliases: Iterable[Iterable[str]] = (), max_paths: int = 64) -> Report:
    """Analyze one entrypoint independently, without importing it.

    Alias groups contain board attribute names, e.g. (("D4", "SDA"),).
    They must come from the user's actual board definition. Unknown branches
    are independent possibilities, not proof of runtime reachability.
    """
    if max_paths < 1:
        raise ValueError("max_paths must be positive")
    analyzer = Analyzer(path, aliases, max_paths, source)
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError) as error:
        analyzer.report.diagnostics.append(Diagnostic(
            "PA900", "error", getattr(error, "lineno", None) or 1,
            getattr(error, "offset", None) or 1, f"Cannot parse source: {error}"))
        return analyzer.report
    try:
        analyzer.block(tree.body, [State()])
    except RecursionError:
        analyzer.emit("PA901", tree, "Analysis stopped: expression nesting exceeds the analyzer limit.")
    analyzer.report.allocations = len(analyzer.allocations)
    analyzer.report.diagnostics.sort(key=lambda d: (d.line, d.column, d.code, d.pin or "", d.message))
    return analyzer.report
