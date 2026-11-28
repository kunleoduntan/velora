# Velora 1.17.1

- **Framework fix:** child rows that a DocType adds while it validates (computed lines, such as a calculation's gas breakdown) now get their parent link and name before saving. Before, saving such a document failed with a database error. Applies to insert, save and submit.
- Includes everything in 1.17.0 (see RELEASE-NOTES-v1.17.0.md).
