# Validation — v1.7.0

- Pytest suite: 38 tests passed.
- Native PDF smoke test: valid PDF signature and non-empty output.
- Native DOCX smoke test: ZIP signature and non-empty output.
- Export template configuration validation tests.
- Existing reporting, publishing, review and dashboard regression tests retained.
- Python source compilation checked.
- All DocType JSON files parsed; duplicate field names checked.
- Source ZIP and release bundle ZIP integrity checked.
- Wheel package import and RECORD integrity checked.

Runtime qualification is still required in the target Velora installation: attachment permissions, template DocType migrations, publication register linking, browser preview, real-world page layout, font/rendering fidelity, and workflow permission integration.
