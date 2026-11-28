# Server Script limits

A Server Script is a small, restricted piece of Python that an administrator attaches to a document event. It is deliberately not a general programming language: no loops, no functions, no imports, no calls except a short allow-list, and attribute access only on `doc.<field>`.

To keep one script from freezing or exhausting a worker, every operation that could grow is also **bounded**:

| Limit | Value | What happens past it |
|---|---|---|
| `range()` | at most 10,000 numbers | "range() may produce at most 10,000 numbers" (`sum(range(10**12))` is one call that nothing can interrupt, so it must never start) |
| A string or list | at most 100,000 items | refused *before* it is allocated (`'x' * 10**10`, `x = x + x` repeated) |
| A whole number | at most 4,096 bits | "a number that is too large" (repeated squaring) |
| Text-format widths | at most 1,000, and no `*` | `'%999999999d' % 1` would allocate a gigabyte |

A script may **read** any column of its document but **write** only the document's own fields: never `docstatus`, `owner`, `name`, `creation` or `modified` (a script must not bypass submit, ownership or naming). Any runtime error (`1/0`, a missing field, a wrong type) is reported as `Server Script 'name' failed: ZeroDivisionError: ...`, never a bare server error. A deliberate `throw("message")` is shown as written.

The compiled script is cached per saved version, so editing a script takes effect immediately and unchanged scripts are not re-parsed on every document event.
