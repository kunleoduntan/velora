"""Frappe-compatible field conditions (`depends_on`, `mandatory_depends_on`, `read_only_depends_on`).

Frappe evaluates these as JavaScript in the browser. Velora evaluates the SAME small, safe subset of JavaScript on the server (this file) and in the Desk
(`frontend/src/conditions.ts`); `tests/fixtures/conditions_corpus.json` is run through both so they cannot drift. Nothing is ever passed to `eval`.

Accepted forms:  `fieldname`            (true when the field has a value)
                 `eval:<expression>`    (a JavaScript expression)
                 `<expression>`         (anything else that contains an operator is read as an expression, as in older Frappe)
Expressions: numbers, 'strings', "strings", true, false, null, undefined, [lists]; doc.field, doc["field"], parent.field, bare field names, `frappe.user`, `frappe.session.user`,
`frappe.user_roles`; ! - + * / %  < <= > >=  == != === !==  && ||  ?:  (...)  `.length`; `.includes() .startsWith() .endsWith() .indexOf() .toLowerCase() .toUpperCase() .trim()`;
functions `cint() flt() cstr()`; `__islocal` (a document that is not saved yet). Anything else is refused when a DocType is saved.
"""
from __future__ import annotations

import math
import re

MAX_LENGTH = 1000
MAX_DEPTH = 60


class ConditionError(ValueError):
    pass


_TOKEN = re.compile(r"""\s*(?:(?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<id>[A-Za-z_$][\w$]*)|(?P<op>===|!==|==|!=|<=|>=|&&|\|\||[-+*/%<>!?:.,()\[\]]))""")
_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_METHODS = {"includes", "startsWith", "endsWith", "indexOf", "toLowerCase", "toUpperCase", "trim"}
_FUNCS = {"cint", "flt", "cstr"}


def _unquote(raw: str) -> str:
    body, out, i = raw[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", body[i + 2:i + 6]):
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(_ESC.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


_WORDS = {"and": ("op", "&&"), "or": ("op", "||"), "not": ("op", "!"), "in": ("op", "in"), "True": ("id", "true"), "False": ("id", "false"), "None": ("id", "null")}


def _tokenize(src: str) -> list:
    """JavaScript tokens. Python-style `and` `or` `not` `in` `not in` `True` `False` `None` are accepted too, because DocTypes written before 0.81.1 used them."""
    toks = _raw_tokens(src)
    out: list = []
    for i, tok in enumerate(toks):
        if tok[0] == "id" and tok[1] in _WORDS:
            if tok[1] == "in" and out and out[-1] == ("op", "!") and i >= 2 and toks[i - 1] == ("id", "not"):
                out[-1] = ("op", "not in")
                continue
            tok = _WORDS[tok[1]]
        out.append(tok)
    return out


def _raw_tokens(src: str) -> list:
    toks, pos = [], 0
    while True:
        if not src[pos:].strip():
            return toks
        m = _TOKEN.match(src, pos)
        if not m:
            raise ConditionError(f"unexpected character near {src[pos:pos + 10].strip()!r}")
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        toks.append(("num", float(text)) if kind == "num" else ("str", _unquote(text)) if kind == "str" else (kind, text))


class _Parser:
    def __init__(self, toks):
        self.t, self.i, self.depth = toks, 0, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if tok[0] is None or (value is not None and tok[1] != value):
            raise ConditionError(f"expected {value!r}" if value else "unexpected end")
        self.i += 1
        return tok

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ConditionError("expression is nested too deeply")

    def parse(self):
        node = self.ternary()
        if self.i != len(self.t):
            raise ConditionError(f"unexpected {self.peek()[1]!r}")
        return node

    def ternary(self):
        self.enter()
        cond = self.binary(0)
        if self.peek() == ("op", "?"):
            self.take()
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            cond = ("cond", cond, a, b)
        self.depth -= 1
        return cond

    LEVELS = [("||",), ("&&",), ("==", "!=", "===", "!=="), ("<", "<=", ">", ">=", "in", "not in"), ("+", "-"), ("*", "/", "%")]

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in self.LEVELS[level]:
            op = self.take()[1]
            left = ("bin", op, left, self.binary(level + 1))
            if op in ("<", "<=", ">", ">=", "==", "!=", "===", "!==", "in", "not in") and self.peek()[0] == "op" and self.peek()[1] in self.LEVELS[level]:
                raise ConditionError("chained comparisons are not supported")
        return left

    def unary(self):
        tok = self.peek()
        if tok == ("op", "!") or tok == ("op", "-") or tok == ("op", "+"):
            self.take()
            self.enter()
            node = ("un", tok[1], self.unary())
            self.depth -= 1
            return node
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while True:
            tok = self.peek()
            if tok == ("op", "."):
                self.take()
                name = self.take()
                if name[0] != "id":
                    raise ConditionError("a name must follow '.'")
                if self.peek() == ("op", "("):
                    if name[1] not in _METHODS:
                        raise ConditionError(f"method {name[1]!r} is not supported")
                    node = ("call", node, name[1], self.args())
                elif name[1] == "length":
                    node = ("len", node)
                else:
                    node = ("get", node, name[1])
            elif tok == ("op", "["):
                self.take()
                key = self.ternary()
                self.take("]")
                node = ("idx", node, key)
            else:
                return node

    def args(self):
        self.take("(")
        out = []
        if self.peek() != ("op", ")"):
            out.append(self.ternary())
            while self.peek() == ("op", ","):
                self.take()
                out.append(self.ternary())
        self.take(")")
        return out

    def primary(self):
        kind, val = self.peek()
        if kind is None:
            raise ConditionError("unexpected end")
        self.take()
        if kind in ("num", "str"):
            return ("lit", val)
        if kind == "op" and val == "(":
            node = self.ternary()
            self.take(")")
            return node
        if kind == "op" and val == "[":
            items = []
            if self.peek() != ("op", "]"):
                items.append(self.ternary())
                while self.peek() == ("op", ","):
                    self.take()
                    items.append(self.ternary())
            self.take("]")
            return ("list", items)
        if kind == "id":
            if val in ("true", "false"):
                return ("lit", val == "true")
            if val in ("null", "undefined"):
                return ("lit", None)
            if val in _FUNCS:
                return ("func", val, self.args())
            if val.startswith("_") and val != "__islocal":
                raise ConditionError(f"{val!r} is not allowed")
            return ("name", val)
        raise ConditionError(f"unexpected {val!r}")


def _parse(expr: str):
    if len(expr) > MAX_LENGTH:
        raise ConditionError("expression is too long")
    node = _Parser(_tokenize(expr)).parse()
    _walk_check(node)
    return node


def _walk_check(node):
    """Static rules: only doc/parent/frappe member access, no underscore names."""
    if node[0] == "get":
        base = node[1]
        if base[0] == "name" and base[1] in ("doc", "parent", "frappe"):
            if node[2].startswith("_") and node[2] != "__islocal":
                raise ConditionError(f"{node[2]!r} is not allowed")
        elif base[0] == "get" and base[1] == ("name", "frappe") and base[2] == "session" and node[2] == "user":
            pass
        elif base[0] == "name" and base[1] not in ("doc", "parent", "frappe"):
            raise ConditionError("only doc.field, parent.field and frappe.user are allowed")
        elif base[0] not in ("name", "get"):
            raise ConditionError("property access is only allowed on doc, parent and frappe")
        elif base[0] == "get" and not (base[1] == ("name", "frappe") and base[2] == "session"):
            raise ConditionError("property access is only allowed on doc, parent and frappe")
    if node[0] == "idx" and not (node[1][0] == "name" and node[1][1] in ("doc", "parent")):
        raise ConditionError("[...] is only allowed on doc and parent")
    for child in node[1:]:
        if isinstance(child, tuple) and child and isinstance(child[0], str):
            _walk_check(child)
        elif isinstance(child, list):
            for c in child:
                if isinstance(c, tuple):
                    _walk_check(c)


def _split(expression) -> tuple[str, str]:
    """(kind, body): kind is 'blank', 'field' or 'expr'."""
    text = str(expression).strip() if expression is not None else ""
    if text.startswith("eval:"):
        body = text[5:].strip()
        return ("expr", body) if body else ("blank", "")
    if not text:
        return "blank", ""
    if re.fullmatch(r"[A-Za-z_]\w*", text) and not text.startswith("_"):
        return "field", text
    return "expr", text


def validate_condition(expression) -> None:
    """Raise ConditionError when a condition uses anything outside the safe subset (called when a DocType is saved)."""
    kind, body = _split(expression)
    if kind == "expr":
        try:
            _parse(body)
        except ConditionError as exc:
            raise ConditionError(f"Invalid or unsupported condition {expression!r}: {exc}") from None
    elif kind == "field" and body.startswith("_"):
        raise ConditionError(f"Invalid condition {expression!r}")


# ---- JavaScript value semantics --------------------------------------------------------------------------------------------------------
def _truthy(v) -> bool:
    if v is None or v is False or v == "" or (isinstance(v, float) and math.isnan(v)):
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0
    return True


def _num(v):
    if v is None or v is False or v == "":
        return 0.0
    if v is True:
        return 1.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0.0
        except ValueError:
            return math.nan
    return math.nan


def _str(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, list):
        return ",".join("" if x is None else _str(x) for x in v)
    return str(v)


def _strict_equals(a, b) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return a is b
    if isinstance(a, str) != isinstance(b, str):
        return False
    return a == b if a is not None or b is not None else True


def _loose_equals(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) or isinstance(b, dict):
        return a is b
    if isinstance(a, list) and isinstance(b, list):
        return a is b
    a, b = (_str(a) if isinstance(a, list) else a), (_str(b) if isinstance(b, list) else b)       # JavaScript compares a list with a scalar through its text
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    na, nb = _num(a), _num(b)
    return na == nb


def _compare(op, a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        x, y = a, b
    else:
        x, y = _num(a), _num(b)
        if math.isnan(x) or math.isnan(y):
            return False
    return x < y if op == "<" else x <= y if op == "<=" else x > y if op == ">" else x >= y


def _plain(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _eval(node, doc, ctx, depth=0):
    if depth > MAX_DEPTH * 4:
        raise ConditionError("too deep")
    k = node[0]
    d = depth + 1
    if k == "lit":
        return node[1]
    if k == "list":
        return [_eval(x, doc, ctx, d) for x in node[1]]
    if k == "name":
        n = node[1]
        if n == "doc":
            return doc
        if n == "parent":
            return ctx.get("parent") or {}
        if n == "frappe":
            return {"user": ctx.get("user"), "user_roles": ctx.get("roles") or [], "session": {"user": ctx.get("user")}}
        if n == "__islocal":
            return bool(ctx.get("islocal", _field(doc, "__islocal")))
        return _field(doc, n)
    if k == "get":
        base = _eval(node[1], doc, ctx, d)
        return _field(base, node[2]) if isinstance(base, (dict, object)) and not isinstance(base, (str, int, float, bool, list)) else None
    if k == "idx":
        key = _eval(node[2], doc, ctx, d)
        base = _eval(node[1], doc, ctx, d)
        return _field(base, key) if isinstance(key, str) else None
    if k == "len":
        v = _eval(node[1], doc, ctx, d)
        return len(v) if isinstance(v, (str, list)) else None
    if k == "un":
        v = _eval(node[2], doc, ctx, d)
        return (not _truthy(v)) if node[1] == "!" else (-_num(v) if node[1] == "-" else _num(v))
    if k == "cond":
        return _eval(node[2] if _truthy(_eval(node[1], doc, ctx, d)) else node[3], doc, ctx, d)
    if k == "func":
        vals = [_eval(x, doc, ctx, d) for x in node[2]]
        v = vals[0] if vals else None
        if node[1] == "cstr":
            return "" if v is None else _str(v)
        n = _num(v)
        n = 0.0 if math.isnan(n) else n
        return float(int(n)) if node[1] == "cint" else n
    if k == "call":
        target = _eval(node[1], doc, ctx, d)
        args = [_eval(x, doc, ctx, d) for x in node[3]]
        return _call(target, node[2], args)
    if k == "bin":
        op = node[1]
        if op == "&&":
            a = _eval(node[2], doc, ctx, d)
            return _eval(node[3], doc, ctx, d) if _truthy(a) else a
        if op == "||":
            a = _eval(node[2], doc, ctx, d)
            return a if _truthy(a) else _eval(node[3], doc, ctx, d)
        a, b = _eval(node[2], doc, ctx, d), _eval(node[3], doc, ctx, d)
        if op == "===":
            return _strict_equals(a, b)
        if op == "!==":
            return not _strict_equals(a, b)
        if op == "==":
            return _loose_equals(a, b)
        if op == "!=":
            return not _loose_equals(a, b)
        if op in ("<", "<=", ">", ">="):
            return _compare(op, a, b)
        if op in ("in", "not in"):                      # the Python spelling `x in [..]` / `x in "text"`
            hit = any(_strict_equals(x, a) or _loose_equals(x, a) for x in b) if isinstance(b, list) else (isinstance(b, str) and _str(a) in b)
            return hit if op == "in" else not hit
        if op == "+":
            if isinstance(a, (str, list)) or isinstance(b, (str, list)):
                return _str(a) + _str(b)
            return _num(a) + _num(b)
        x, y = _num(a), _num(b)
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            return (x / y) if y else (math.nan if x == 0 or math.isnan(x) else math.inf * (1 if x > 0 else -1))
        return math.fmod(x, y) if y else math.nan
    raise ConditionError(f"unsupported {k}")


def _call(target, name, args):
    a0 = args[0] if args else None
    if isinstance(target, list):
        if name == "includes":
            return any(_strict_equals(x, a0) or (isinstance(x, (int, float)) and isinstance(a0, (int, float)) and not isinstance(x, bool) and not isinstance(a0, bool) and x == a0) for x in target)
        if name == "indexOf":
            for i, x in enumerate(target):
                if _strict_equals(x, a0) or (isinstance(x, (int, float)) and isinstance(a0, (int, float)) and not isinstance(x, bool) and not isinstance(a0, bool) and x == a0):
                    return i
            return -1
        raise ConditionError(f"{name} is not available on a list")
    if isinstance(target, str):
        if name == "includes":
            return _str(a0) in target
        if name == "startsWith":
            return target.startswith(_str(a0))
        if name == "endsWith":
            return target.endswith(_str(a0))
        if name == "indexOf":
            return target.find(_str(a0))
        if name == "toLowerCase":
            return target.lower()
        if name == "toUpperCase":
            return target.upper()
        if name == "trim":
            return target.strip()
    raise ConditionError(f"{name} cannot be used here")


def _field(source, key):
    if source is None or not isinstance(key, str) or (key.startswith("_") and key != "__islocal"):
        return None
    v = source.get(key) if isinstance(source, dict) else getattr(source, key, None) if not isinstance(source, (str, int, float, bool, list)) else None
    if callable(v):
        return None
    return _plain(v) if isinstance(v, float) else v


def evaluate_condition(expression, doc, context: dict | None = None) -> bool:
    """True when the condition holds for `doc`. A blank condition, or anything that fails to evaluate, is False (as in Frappe, where an error is logged and the field stays plain).

    `context` may carry `user`, `roles`, `parent` (the parent document for a child row) and `islocal`."""
    kind, body = _split(expression)
    if kind == "blank":
        return False
    try:
        if kind == "field":
            return _truthy(_field(doc, body))
        return _truthy(_eval(_parse(body), doc, context or {}))
    except (ConditionError, RecursionError, ArithmeticError, ValueError, TypeError):
        return False
