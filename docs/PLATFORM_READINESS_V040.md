# Platform readiness and deployment integrity (v0.40)

## Readiness inspection

Run from a workspace:

```bash
velora readiness
```

The command returns structured JSON with `ready`, `warning`, or `fail` overall status. Checks include common configuration, registered app source folders, site configuration JSON, supported database configuration shape, POSIX config permissions, disk space and workspace operational directories. It is a static inspection: it does not open tenant databases or change settings.

## Deployment integrity manifest

Create a credential-free inventory:

```bash
velora manifest create
```

Verify the inventory after copying or deploying source:

```bash
velora manifest verify
```

An alternate path can be supplied to either command. The manifest records framework version, app versions, relative file paths, byte sizes and SHA-256 digests. It deliberately excludes site and control-plane configuration, master keys, `.env` files, database files, bytecode and generated dependency/build directories. Store manifests alongside release artifacts and keep them in version control or a trusted release store.

A manifest is an integrity inventory, not a digital signature. Protect the manifest itself and distribute it through a trusted channel; use signed release attestations for authenticity requirements.

## Recommended production operating procedure

1. Run `velora doctor` and `velora readiness` before deployment.
2. Take a database backup and separately protect the platform master key.
3. Create and retain a deployment manifest for the exact application source being deployed.
4. Apply updates using `velora update` so database migrations and rollback safeguards are used.
5. Run `velora manifest verify` against the deployed source.
6. Run `velora doctor`, confirm all companies are upgraded, and perform a controlled login and transaction smoke test.
7. Periodically perform restore drills; a successful backup command alone does not prove recoverability.

## Limitations
Readiness checks are structural and do not prove database connectivity, TLS correctness, reverse-proxy security, monitoring delivery, backup restorability or application-specific business correctness. These require environment-level checks and operational drills.
