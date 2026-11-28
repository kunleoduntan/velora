# Velora AI Developer Studio — Governance and operating model

Velora AI Developer Studio provides a staged set of AI-assisted development and data tools. Capabilities are exposed by release level and role; installed applications can extend the advisor layer without bypassing framework controls.

## Release levels

- **0.89.0 — Agent Studio:** define named agents, instructions, role access and tool allowlists. Agents are advisory and cannot independently invoke tools.
- **0.90.0 — Metadata and Code Copilot:** generate DocType JSON and source-code drafts. DocType JSON is validated with the native metadata validator. Publishing is a separate developer-mode action through the DocType Creator. Python output is syntax parsed. Generated code is never executed by the AI service.
- **0.91.0 — Governed Database and Command Assistant:** inspect registered DocType schemas; query records through the permission-aware document query engine; preview and confirm create/update/delete operations limited to draft documents; obtain commands from a fixed approved Velora CLI catalogue.

## Database safeguards

- No raw SQL execution is exposed by the AI Developer Studio.
- Reads use `get_list`, preserving DocType read permissions, row policies and field visibility.
- Mutations use the normal Document engine and its validation, permission, link, audit and transaction lifecycle.
- AI document actions can create, update or delete drafts only. Submitted and cancelled records are never modified or deleted through these endpoints.
- Every write requires a preview, a short-lived single-use confirmation token, and confirmation by the same user who requested the preview.
- Draft creation does not submit documents, post accounting entries, approve workflows or trigger financial posting unless the document's own standard insert hooks require it. No AI tool can call submit or post.

## Code and metadata safeguards

- Generated DocType JSON is validated before it is returned. It is not automatically persisted.
- Publishing DocTypes is separate, requires developer mode and writes only through the existing DocType Creator.
- Generated code is returned as an untrusted draft. Python receives syntax parsing; code is not imported, executed or installed.
- SQL code generation is limited to read-only SELECT drafts. It is not a database execution pathway.

## Command safeguards

The command advisor can only return exact commands from the approved Velora CLI catalogue. It does not start subprocesses, invoke a shell, pipe output, redirect files, install packages or execute commands. Operators must review the workspace, company/site and backup status before running a command.

## AI agents

Agent definitions are tenant-local and include role gates, tool allowlists, instructions and enabled status. A saved allowlist is a declaration of which Studio tools an agent may be used with; it is not an execution grant. Each operation is still checked by the tool endpoint and normal Velora permissions. Secrets and API credentials are never included in agent prompts or audit records.
