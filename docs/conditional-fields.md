# Conditional fields (`depends_on`, `mandatory_depends_on`, `read_only_depends_on`)

These work as in Frappe. Velora evaluates the same safe subset of JavaScript on the server and in the Desk; nothing is passed to `eval`.

| Write | Meaning |
|---|---|
| `is_autoname` | the field has a value (truthy) |
| `eval:doc.status === "Open" && doc.amount > 100` | a JavaScript expression |
| `eval:!doc.name`, `eval:doc.qty == 0 \|\| doc.rate` | `!`, `&&`, `\|\|`, `==`, `===`, `!=`, `!==`, `<` `<=` `>` `>=` |
| `eval:doc.amount > 100 ? true : false` | conditional |
| `eval:["Open","Draft"].includes(doc.status)` | lists; `.includes .indexOf .startsWith .endsWith .toLowerCase .toUpperCase .trim .length` |
| `eval:cint(doc.qty) > 0` | `cint()`, `flt()`, `cstr()` |
| `eval:frappe.user === "a@b.com"`, `eval:frappe.user_roles.includes("Accounts Manager")` | the signed-in user and the roles they hold in this company |
| `eval:parent.status === "Open"` | the parent document, inside a child row |
| `eval:__islocal` | the document is not saved yet |

JavaScript rules apply: `"1" == 1` is true, `"1" === 1` is false, `0`, `""`, `null` are falsy. A missing field reads as `null` (Velora does not distinguish `null` from `undefined`).

**Refused when the DocType is saved:** assignments, function definitions, `this`, `window`, other function calls (`alert()`, `eval()`), `typeof`, template strings, names starting with `_` (except `__islocal`), chained comparisons (`1 < 2 < 3`), and expressions over 1000 characters. A condition that fails at run time counts as false.

The server enforces `mandatory_depends_on` when saving, so hiding a field in the browser is never the only protection.
