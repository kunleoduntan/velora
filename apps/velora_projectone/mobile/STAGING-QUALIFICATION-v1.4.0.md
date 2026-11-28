# Live staging qualification — ProjectOne Mobile v1.4.0

This runner exercises the supplied Velora Framework v1.13.0 authentication API against a real HTTPS staging deployment. It is separate from offline source-contract tests.

## Safety

- Use a dedicated, non-production staging account.
- Do not use a platform administrator account unless it is a dedicated test identity.
- Do not commit credentials, TOTP codes, `.env` files, or bearer tokens.
- Run only against a staging environment you administer.
- The runner never prints passwords, TOTP values, or bearer tokens.
- It creates a real session and revokes it at the end. If an intermediate check fails, it attempts best-effort logout.

## Configure

In the mobile app directory, set these variables in your local shell:

```bash
export EXPO_PUBLIC_PROJECTONE_API_BASE="https://YOUR-STAGING-HOST"
export VELORA_TEST_EMAIL="mobile-test@example.com"
export VELORA_TEST_PASSWORD="your-staging-password"
# Set only when the test user has TOTP enabled:
export VELORA_TEST_TOTP="123456"
# Optional: an additional company the test user is authorised to access:
export VELORA_TEST_SWITCH_COMPANY_ID="COMP-002"
```

Do not place credentials in `app.config.js`, `eas.json`, Expo public variables, source control, or build artifacts. Only the API base URL is a public build-time setting. Test credentials are consumed locally by the qualification script.

## Run

```bash
node scripts/qualify-staging.mjs
```

The runner checks public auth configuration, anonymous-session rejection, password sign-in (and TOTP when configured), user/company profile, bearer session restoration, optional authorised company switching and restoration, server-side logout, and rejection of a revoked token.

The script does not deliberately submit invalid passwords because repeated failures can trigger account lockout. Validate lockout using the Framework's controlled automated tests or a separately approved test procedure.

## Limits

This does not replace physical-device testing. It does not test SecureStore behaviour on a device, Android/iOS network lifecycle, push notifications, or the complete ProjectOne workflow permission matrix. A successful run establishes live API reachability and the exercised server authentication/session flows for the configured staging account and host.
