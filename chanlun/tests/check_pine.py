#!/usr/bin/env python3
"""Conservative source checks, NOT a Pine compiler or execution engine.

Checks lexical delimiters, local f_* references/order, user type constructor
arity, forbidden local plot declarations, and a few definite v6 mistakes.
Array-size loop reviews are warnings: this tool performs no data-flow proof.
Run: python3 chanlun/tests/check_pine.py [chanlun/chanlun_complete.pine]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys


@dataclass
class Finding:
    level: str
    line: int
    message: str


def mask_source(source: str) -> tuple[str, list[Finding]]:
    """Preserve columns/newlines while masking comments and quoted strings."""
    result = list(source)
    findings = []
    i = 0
    line = 1
    while i < len(source):
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
        elif source.startswith("//", i):
            while i < len(source) and source[i] != "\n":
                result[i] = " "
                i += 1
        elif c in "\"'":
            quote, start, start_line = c, i, line
            triple = source.startswith(c * 3, i)
            terminator = c * (3 if triple else 1)
            for _ in terminator:
                result[i] = " "
                i += 1
            closed = False
            while i < len(source):
                if source.startswith(terminator, i):
                    for _ in terminator:
                        result[i] = " "
                        i += 1
                    closed = True
                    break
                if source[i] == "\n":
                    line += 1
                else:
                    result[i] = " "
                if source[i] == "\\" and i + 1 < len(source):
                    i += 1
                    if source[i] != "\n":
                        result[i] = " "
                i += 1
            if not closed:
                findings.append(Finding("ERROR", start_line, "Unclosed quoted string"))
        else:
            i += 1
    return "".join(result), findings


def check(source: str, fragment: bool = False) -> list[Finding]:
    masked, findings = mask_source(source)
    lines = masked.splitlines()
    if not fragment:
        versions = re.findall(r"(?m)^\s*//@version=(\d+)\s*$", source)
        if versions != ["6"]:
            findings.append(Finding("ERROR", 1, "Expected exactly one Pine v6 version annotation"))
        declarations = re.findall(r"(?m)^(?:indicator|strategy|library)\s*\(", masked)
        if len(declarations) != 1:
            findings.append(Finding("ERROR", 1, "Expected exactly one global script declaration"))

    # Angle brackets are type templates/comparisons, not lexical brackets.
    stack = []
    closes = {')': '(', ']': '[', '}': '{'}
    line = 1
    for c in masked:
        if c == "\n":
            line += 1
        elif c in "([{":
            stack.append((c, line))
        elif c in ")]}":
            if not stack or stack[-1][0] != closes[c]:
                findings.append(Finding("ERROR", line, "Unmatched closing delimiter " + c))
            else:
                stack.pop()
    for bracket, number in stack:
        findings.append(Finding("ERROR", number, "Unclosed delimiter " + bracket))

    function_pattern = re.compile(r"^(?:(?:export )?method )?([A-Za-z_]\w*)\s*\((.*)\)\s*=>")
    definitions = {}
    methods = set()
    types = {}
    active_type = None
    for number, line in enumerate(lines, 1):
        match = function_pattern.match(line)
        if match:
            name = match.group(1)
            definitions.setdefault(name, []).append(number)
            if line.startswith("method ") or line.startswith("export method "):
                methods.add(name)
        type_match = re.match(r"^type\s+([A-Za-z_]\w*)\s*$", line)
        if type_match:
            active_type = type_match.group(1)
            types[active_type] = []
        elif line.strip() and not line.startswith((" ", "\t")):
            active_type = None
        elif active_type and line.strip():
            field = re.match(r"^\s+(?:varip\s+)?(?:[\w.]+(?:<[^>]+>)?\s+)?([A-Za-z_]\w*)(?:\s*=.*)?$", line)
            if field:
                types[active_type].append(field.group(1))

    global_only = r"(?:indicator|strategy|library|plot|hline|fill|plotshape|plotchar|plotarrow|plotbar|plotcandle|barcolor|bgcolor|alertcondition)"
    for number, line in enumerate(lines, 1):
        declaration = function_pattern.match(line)
        if re.search(r"\b(?:return|class|def)\b", line):
            findings.append(Finding("ERROR", number, "Non-Pine/reserved return/class/def token"))
        if re.search(r"\bbool\s+\w+\s*=\s*na\b(?!\s*\()", line):
            findings.append(Finding("ERROR", number, "Pine v6 bool cannot be na"))
        if re.search(r"\btransp\s*=", line):
            findings.append(Finding("ERROR", number, "Removed Pine v6 transp argument"))
        if line.startswith((" ", "\t")) and re.search(r"(?<![\w.])" + global_only + r"\s*\(", line):
            findings.append(Finding("ERROR", number, "Global-only declaration/plot/alertcondition called in a local block"))
        for call in re.finditer(r"(?<![\w.])(f_[A-Za-z_]\w*)\s*\(", line):
            name = call.group(1)
            if declaration and declaration.group(1) == name and call.start() == line.index(name):
                continue
            if name not in definitions:
                if not fragment:
                    findings.append(Finding("ERROR", number, "Undefined local function " + name))
            elif min(definitions[name]) >= number:
                findings.append(Finding("ERROR", number, "Function called before definition or recursive: " + name))
        for method in re.finditer(r"\.([A-Za-z_]\w*)\s*\(", line):
            name = method.group(1)
            if name in methods and min(definitions[name]) >= number:
                findings.append(Finding("ERROR", number, "User method called before definition or recursive: " + name))
        if re.search(r"\bfor\s+\w+\s*=.*\bto\b.*\.size\(\)", line):
            findings.append(Finding("REVIEW", number, "Dynamic array-size loop bound: verify empty guard and no size mutation during traversal"))
        if re.search(r"\b(?:for|while)\b", line) and re.search(r"\.(?:push|pop|shift|unshift|remove)\s*\(", line):
            findings.append(Finding("REVIEW", number, "Mutation in loop condition: verify termination under Pine v6 dynamic bounds"))

    # Check constructor argument counts without interpreting expressions/types.
    for call in re.finditer(r"\b([A-Za-z_]\w*)\.new\s*\(", masked):
        typename = call.group(1)
        if typename not in types:
            continue
        begin, depth, cursor, arg_start = call.end(), 1, call.end(), call.end()
        args = []
        while cursor < len(masked) and depth:
            c = masked[cursor]
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            if (c == ',' and depth == 1) or depth == 0:
                args.append(source[arg_start:cursor].strip())
                arg_start = cursor + 1
            cursor += 1
        if args == ['']:
            args = []
        number = masked.count('\n', 0, call.start()) + 1
        if len(args) > len(types[typename]):
            findings.append(Finding("ERROR", number, f"{typename}.new has {len(args)} arguments for {len(types[typename])} fields"))
        names = []
        for arg in args:
            named = re.match(r"^([A-Za-z_]\w*)\s*=(?!=)", arg)
            if named:
                name = named.group(1)
                if name not in types[typename]:
                    findings.append(Finding("ERROR", number, f"Unknown {typename}.new field {name}"))
                if name in names:
                    findings.append(Finding("ERROR", number, f"Repeated {typename}.new field {name}"))
                names.append(name)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).parents[1] / "chanlun_complete.pine")
    parser.add_argument("--fragment", action="store_true", help="Allow missing header and cross-fragment functions")
    args = parser.parse_args()
    findings = check(args.path.read_text(encoding="utf-8"), args.fragment)
    for item in findings:
        print(f"{args.path}:{item.line}: {item.level}: {item.message}")
    errors = sum(item.level == "ERROR" for item in findings)
    reviews = sum(item.level == "REVIEW" for item in findings)
    print(f"Static source check: {errors} errors, {reviews} manual reviews. This is NOT TradingView compilation or runtime validation.")
    return int(errors > 0)


if __name__ == "__main__":
    sys.exit(main())
