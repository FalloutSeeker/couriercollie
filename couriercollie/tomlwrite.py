"""Write TOML.

Python can read TOML (tomllib) but not write it, and the usual writer (tomli-w) isn't installed on Fedora by default.
The settings file only needs strings, numbers, booleans, tables and arrays of tables, so this covers exactly that.
"""

import re

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else _string(key)


def _string(value: str) -> str:
    out = []
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _value(value) -> str:
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    raise TypeError(f"can’t write {type(value).__name__} to TOML")


def _is_table_array(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def _write_table(lines: list[str], table: dict, prefix: str) -> None:
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict) and not _is_table_array(v)}
    for k, v in scalars.items():
        lines.append(f"{_key(k)} = {_value(v)}")
    for k, v in table.items():
        name = f"{prefix}.{_key(k)}" if prefix else _key(k)
        if isinstance(v, dict):
            lines.extend(["", f"[{name}]"])
            _write_table(lines, v, name)
        elif _is_table_array(v):
            for item in v:
                lines.extend(["", f"[[{name}]]"])
                _write_table(lines, item, name)


def dumps(data: dict) -> str:
    lines: list[str] = []
    _write_table(lines, data, "")
    return "\n".join(lines).lstrip("\n") + "\n"
