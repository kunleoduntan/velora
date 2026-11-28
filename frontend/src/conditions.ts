/**
 * Frappe-compatible field conditions (depends_on, mandatory_depends_on, read_only_depends_on).
 * The same safe subset of JavaScript as velora/meta/conditions.py, written as a tokenizer + recursive-descent parser: nothing is ever passed to eval or Function.
 * tests/fixtures/conditions_corpus.json (expected values produced by real JavaScript) is run through BOTH implementations.
 */
export interface ConditionContext { user?: string | null; roles?: string[]; parent?: Record<string, unknown> | null; islocal?: boolean }
type Val = unknown;
type Node =
  | { k: "lit"; v: Val } | { k: "list"; items: Node[] } | { k: "name"; n: string } | { k: "get"; base: Node; key: string } | { k: "idx"; base: Node; key: Node }
  | { k: "len"; base: Node } | { k: "un"; op: string; a: Node } | { k: "cond"; c: Node; a: Node; b: Node } | { k: "func"; n: string; args: Node[] }
  | { k: "call"; base: Node; n: string; args: Node[] } | { k: "bin"; op: string; a: Node; b: Node };
type Tok = [string, string | number];

export class ConditionError extends Error {}
const MAX_LENGTH = 1000, MAX_DEPTH = 60;
const METHODS = new Set(["includes", "startsWith", "endsWith", "indexOf", "toLowerCase", "toUpperCase", "trim"]);
const FUNCS = new Set(["cint", "flt", "cstr"]);
const TOKEN = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|([A-Za-z_$][\w$]*)|(===|!==|==|!=|<=|>=|&&|\|\||[-+*/%<>!?:.,()[\]]))/y;
const ESC: Record<string, string> = { n: "\n", t: "\t", r: "\r", b: "\b", f: "\f", v: "\v", "0": "\0" };

function unquote(raw: string): string {
  const body = raw.slice(1, -1); let out = "";
  for (let i = 0; i < body.length;) {
    const c = body[i];
    if (c === "\\" && i + 1 < body.length) {
      const n = body[i + 1];
      if (n === "u" && /^[0-9a-fA-F]{4}$/.test(body.slice(i + 2, i + 6))) { out += String.fromCharCode(parseInt(body.slice(i + 2, i + 6), 16)); i += 6; continue; }
      out += ESC[n] ?? n; i += 2;
    } else { out += c; i += 1; }
  }
  return out;
}

const WORDS: Record<string, Tok> = { and: ["op", "&&"], or: ["op", "||"], not: ["op", "!"], in: ["op", "in"], True: ["id", "true"], False: ["id", "false"], None: ["id", "null"] };
/** JavaScript tokens; Python-style and/or/not/in/not in/True/False/None are accepted too, because DocTypes written before 0.81.1 used them. */
function tokenize(src: string): Tok[] {
  const raw = rawTokens(src); const out: Tok[] = [];
  raw.forEach((tok, i) => {
    if (tok[0] === "id" && Object.prototype.hasOwnProperty.call(WORDS, tok[1] as string)) {
      const last = out[out.length - 1];
      if (tok[1] === "in" && last && last[0] === "op" && last[1] === "!" && i >= 2 && raw[i - 1][0] === "id" && raw[i - 1][1] === "not") { out[out.length - 1] = ["op", "not in"]; return; }
      out.push(WORDS[tok[1] as string]); return;
    }
    out.push(tok);
  });
  return out;
}
function rawTokens(src: string): Tok[] {
  const toks: Tok[] = []; let pos = 0;
  for (;;) {
    if (!src.slice(pos).trim()) return toks;
    TOKEN.lastIndex = pos;
    const m = TOKEN.exec(src);
    if (!m) throw new ConditionError(`unexpected character near ${src.slice(pos, pos + 10).trim()}`);
    pos = TOKEN.lastIndex;
    if (m[1] !== undefined) toks.push(["num", parseFloat(m[1])]);
    else if (m[2] !== undefined) toks.push(["str", unquote(m[2])]);
    else if (m[3] !== undefined) toks.push(["id", m[3]]);
    else toks.push(["op", m[4]]);
  }
}

const LEVELS = [["||"], ["&&"], ["==", "!=", "===", "!=="], ["<", "<=", ">", ">=", "in", "not in"], ["+", "-"], ["*", "/", "%"]];
const CMP = new Set(["<", "<=", ">", ">=", "==", "!=", "===", "!==", "in", "not in"]);

class Parser {
  i = 0; depth = 0;
  constructor(private t: Tok[]) {}
  peek(): Tok | [null, null] { return this.i < this.t.length ? this.t[this.i] : [null, null]; }
  is(kind: string, v: string) { const p = this.peek(); return p[0] === kind && p[1] === v; }
  take(v?: string): Tok {
    const p = this.peek();
    if (p[0] === null || (v !== undefined && p[1] !== v)) throw new ConditionError(v ? `expected ${v}` : "unexpected end");
    this.i++; return p as Tok;
  }
  enter() { if (++this.depth > MAX_DEPTH) throw new ConditionError("expression is nested too deeply"); }
  parse(): Node { const n = this.ternary(); if (this.i !== this.t.length) throw new ConditionError(`unexpected ${this.peek()[1]}`); return n; }
  ternary(): Node {
    this.enter();
    let c = this.binary(0);
    if (this.is("op", "?")) { this.take(); const a = this.ternary(); this.take(":"); const b = this.ternary(); c = { k: "cond", c, a, b }; }
    this.depth--; return c;
  }
  binary(level: number): Node {
    if (level === LEVELS.length) return this.unary();
    let left = this.binary(level + 1);
    while (this.peek()[0] === "op" && LEVELS[level].includes(this.peek()[1] as string)) {
      const op = this.take()[1] as string;
      left = { k: "bin", op, a: left, b: this.binary(level + 1) };
      if (CMP.has(op) && this.peek()[0] === "op" && LEVELS[level].includes(this.peek()[1] as string)) throw new ConditionError("chained comparisons are not supported");
    }
    return left;
  }
  unary(): Node {
    const p = this.peek();
    if (p[0] === "op" && (p[1] === "!" || p[1] === "-" || p[1] === "+")) { this.take(); this.enter(); const n: Node = { k: "un", op: p[1] as string, a: this.unary() }; this.depth--; return n; }
    return this.postfix();
  }
  args(): Node[] {
    this.take("("); const out: Node[] = [];
    if (!this.is("op", ")")) { out.push(this.ternary()); while (this.is("op", ",")) { this.take(); out.push(this.ternary()); } }
    this.take(")"); return out;
  }
  postfix(): Node {
    let node = this.primary();
    for (;;) {
      if (this.is("op", ".")) {
        this.take(); const name = this.take();
        if (name[0] !== "id") throw new ConditionError("a name must follow '.'");
        const nm = name[1] as string;
        if (this.is("op", "(")) { if (!METHODS.has(nm)) throw new ConditionError(`method ${nm} is not supported`); node = { k: "call", base: node, n: nm, args: this.args() }; }
        else if (nm === "length") node = { k: "len", base: node };
        else node = { k: "get", base: node, key: nm };
      } else if (this.is("op", "[")) { this.take(); const key = this.ternary(); this.take("]"); node = { k: "idx", base: node, key }; }
      else return node;
    }
  }
  primary(): Node {
    const [kind, val] = this.peek();
    if (kind === null) throw new ConditionError("unexpected end");
    this.take();
    if (kind === "num" || kind === "str") return { k: "lit", v: val };
    if (kind === "op" && val === "(") { const n = this.ternary(); this.take(")"); return n; }
    if (kind === "op" && val === "[") {
      const items: Node[] = [];
      if (!this.is("op", "]")) { items.push(this.ternary()); while (this.is("op", ",")) { this.take(); items.push(this.ternary()); } }
      this.take("]"); return { k: "list", items };
    }
    if (kind === "id") {
      const v = val as string;
      if (v === "true" || v === "false") return { k: "lit", v: v === "true" };
      if (v === "null" || v === "undefined") return { k: "lit", v: null };
      if (FUNCS.has(v)) return { k: "func", n: v, args: this.args() };
      if (v.startsWith("_") && v !== "__islocal") throw new ConditionError(`${v} is not allowed`);
      return { k: "name", n: v };
    }
    throw new ConditionError(`unexpected ${val}`);
  }
}

const isFrappeSession = (n: Node) => n.k === "get" && n.key === "session" && n.base.k === "name" && n.base.n === "frappe";
function check(node: Node): void {
  if (node.k === "get") {
    const b = node.base;
    if (b.k === "name" && ["doc", "parent", "frappe"].includes(b.n)) { if (node.key.startsWith("_") && node.key !== "__islocal") throw new ConditionError(`${node.key} is not allowed`); }
    else if (isFrappeSession(b) && node.key === "user") { /* frappe.session.user */ }
    else if (b.k === "name") throw new ConditionError("only doc.field, parent.field and frappe.user are allowed");
    else if (b.k !== "get") throw new ConditionError("property access is only allowed on doc, parent and frappe");
    else if (!isFrappeSession(b)) throw new ConditionError("property access is only allowed on doc, parent and frappe");
  }
  if (node.k === "idx" && !(node.base.k === "name" && (node.base.n === "doc" || node.base.n === "parent"))) throw new ConditionError("[...] is only allowed on doc and parent");
  switch (node.k) {
    case "list": node.items.forEach(check); break;
    case "get": case "len": check(node.base); break;
    case "idx": check(node.base); check(node.key); break;
    case "un": check(node.a); break;
    case "cond": check(node.c); check(node.a); check(node.b); break;
    case "func": node.args.forEach(check); break;
    case "call": check(node.base); node.args.forEach(check); break;
    case "bin": check(node.a); check(node.b); break;
  }
}
function parse(expr: string): Node {
  if (expr.length > MAX_LENGTH) throw new ConditionError("expression is too long");
  const node = new Parser(tokenize(expr)).parse(); check(node); return node;
}
function split(expression: unknown): ["blank" | "field" | "expr", string] {
  const text = expression === null || expression === undefined ? "" : String(expression).trim();
  if (text.startsWith("eval:")) { const body = text.slice(5).trim(); return body ? ["expr", body] : ["blank", ""]; }
  if (!text) return ["blank", ""];
  if (/^[A-Za-z_]\w*$/.test(text) && !text.startsWith("_")) return ["field", text];
  return ["expr", text];
}
export function validateCondition(expression: unknown): void {
  const [kind, body] = split(expression);
  if (kind === "expr") { try { parse(body); } catch (e) { if (e instanceof ConditionError) throw new ConditionError(`Invalid or unsupported condition ${String(expression)}: ${e.message}`); throw e; } }
}

// ---- JavaScript value semantics (kept identical to the Python module) -----------------------------------------------------------------
const isObj = (v: Val): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
function truthy(v: Val): boolean {
  if (v === null || v === undefined || v === false || v === "") return false;
  if (typeof v === "number") return v !== 0 && !Number.isNaN(v);
  return true;
}
function num(v: Val): number {
  if (v === null || v === undefined || v === false || v === "") return 0;
  if (v === true) return 1;
  if (typeof v === "number") return v;
  if (typeof v === "string") { const s = v.trim(); return s ? (Number.isNaN(Number(s)) ? NaN : Number(s)) : 0; }
  return NaN;
}
function str(v: Val): string {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return v.map((x) => (x === null || x === undefined ? "" : str(x))).join(",");
  return String(v);
}
function strictEq(a: Val, b: Val): boolean {
  if (a === undefined) a = null; if (b === undefined) b = null;
  if (typeof a === "boolean" !== (typeof b === "boolean")) return false;
  if (Array.isArray(a) || Array.isArray(b) || isObj(a) || isObj(b)) return a === b;
  if (typeof a === "string" !== (typeof b === "string")) return false;
  return a === b;
}
function looseEq(a: Val, b: Val): boolean {
  if (a === undefined) a = null; if (b === undefined) b = null;
  if (a === null || b === null) return a === null && b === null;
  if (isObj(a) || isObj(b)) return a === b;
  if (Array.isArray(a) && Array.isArray(b)) return a === b;
  if (Array.isArray(a)) a = str(a); if (Array.isArray(b)) b = str(b);
  if (typeof a === "string" && typeof b === "string") return a === b;
  return num(a) === num(b);
}
function compare(op: string, a: Val, b: Val): boolean {
  let x: string | number, y: string | number;
  if (typeof a === "string" && typeof b === "string") { x = a; y = b; } else { x = num(a); y = num(b); if (Number.isNaN(x) || Number.isNaN(y)) return false; }
  return op === "<" ? x < y : op === "<=" ? x <= y : op === ">" ? x > y : x >= y;
}
function field(source: Val, key: Val): Val {
  if (source === null || source === undefined || typeof key !== "string" || (key.startsWith("_") && key !== "__islocal")) return null;
  if (typeof source !== "object" || Array.isArray(source)) return null;
  if (!Object.prototype.hasOwnProperty.call(source, key)) return null;
  const v = (source as Record<string, unknown>)[key];
  return typeof v === "function" ? null : (v === undefined ? null : v);
}
const numEq = (x: Val, y: Val) => strictEq(x, y) || (typeof x === "number" && typeof y === "number" && x === y);
function callMethod(target: Val, name: string, args: Val[]): Val {
  const a0 = args[0];
  if (Array.isArray(target)) {
    if (name === "includes") return target.some((x) => numEq(x, a0));
    if (name === "indexOf") return target.findIndex((x) => numEq(x, a0));
    throw new ConditionError(`${name} is not available on a list`);
  }
  if (typeof target === "string") {
    if (name === "includes") return target.includes(str(a0));
    if (name === "startsWith") return target.startsWith(str(a0));
    if (name === "endsWith") return target.endsWith(str(a0));
    if (name === "indexOf") return target.indexOf(str(a0));
    if (name === "toLowerCase") return target.toLowerCase();
    if (name === "toUpperCase") return target.toUpperCase();
    if (name === "trim") return target.trim();
  }
  throw new ConditionError(`${name} cannot be used here`);
}
function run(node: Node, doc: Val, ctx: ConditionContext, depth = 0): Val {
  if (depth > MAX_DEPTH * 4) throw new ConditionError("too deep");
  const d = depth + 1;
  switch (node.k) {
    case "lit": return node.v;
    case "list": return node.items.map((x) => run(x, doc, ctx, d));
    case "name":
      if (node.n === "doc") return doc;
      if (node.n === "parent") return ctx.parent ?? {};
      if (node.n === "frappe") return { user: ctx.user ?? null, user_roles: ctx.roles ?? [], session: { user: ctx.user ?? null } };
      if (node.n === "__islocal") return ctx.islocal !== undefined ? Boolean(ctx.islocal) : Boolean(field(doc, "__islocal"));
      return field(doc, node.n);
    case "get": return field(run(node.base, doc, ctx, d), node.key);
    case "idx": { const key = run(node.key, doc, ctx, d); return typeof key === "string" ? field(run(node.base, doc, ctx, d), key) : null; }
    case "len": { const v = run(node.base, doc, ctx, d); return typeof v === "string" || Array.isArray(v) ? v.length : null; }
    case "un": { const v = run(node.a, doc, ctx, d); return node.op === "!" ? !truthy(v) : node.op === "-" ? -num(v) : num(v); }
    case "cond": return run(truthy(run(node.c, doc, ctx, d)) ? node.a : node.b, doc, ctx, d);
    case "func": {
      const v = node.args.length ? run(node.args[0], doc, ctx, d) : null;
      if (node.n === "cstr") return v === null || v === undefined ? "" : str(v);
      let n = num(v); if (Number.isNaN(n)) n = 0;
      return node.n === "cint" ? Math.trunc(n) : n;
    }
    case "call": return callMethod(run(node.base, doc, ctx, d), node.n, node.args.map((x) => run(x, doc, ctx, d)));
    case "bin": {
      const op = node.op;
      if (op === "&&") { const a = run(node.a, doc, ctx, d); return truthy(a) ? run(node.b, doc, ctx, d) : a; }
      if (op === "||") { const a = run(node.a, doc, ctx, d); return truthy(a) ? a : run(node.b, doc, ctx, d); }
      const a = run(node.a, doc, ctx, d), b = run(node.b, doc, ctx, d);
      if (op === "===") return strictEq(a, b);
      if (op === "!==") return !strictEq(a, b);
      if (op === "==") return looseEq(a, b);
      if (op === "!=") return !looseEq(a, b);
      if (op === "<" || op === "<=" || op === ">" || op === ">=") return compare(op, a, b);
      if (op === "in" || op === "not in") {                                  // the Python spelling `x in [..]` / `x in "text"`
        const hit = Array.isArray(b) ? b.some((x) => strictEq(x, a) || looseEq(x, a)) : typeof b === "string" && str(a).length >= 0 && b.includes(str(a));
        return op === "in" ? hit : !hit;
      }
      if (op === "+") return typeof a === "string" || typeof b === "string" || Array.isArray(a) || Array.isArray(b) ? str(a) + str(b) : num(a) + num(b);
      const x = num(a), y = num(b);
      return op === "-" ? x - y : op === "*" ? x * y : op === "/" ? x / y : x % y;
    }
  }
}

/** True when the condition holds for `doc`. A blank condition, or one that cannot be evaluated, is false (as in Frappe, where an error is logged). */
export function evaluateCondition(expression: string | undefined | null, doc: Record<string, unknown>, context: ConditionContext = {}): boolean {
  const [kind, body] = split(expression);
  if (kind === "blank") return false;
  try {
    if (kind === "field") return truthy(field(doc, body));
    return truthy(run(parse(body), doc, context));
  } catch { return false; }
}
