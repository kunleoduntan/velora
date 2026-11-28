# Android mobile configuration — v1.4.0

The Android app authenticates directly against the existing Velora Framework API.

- API base: `https://projectone.yourdomain.com` by default.
- Environment override: `EXPO_PUBLIC_PROJECTONE_API_BASE`.
- Android application ID: `com.velora.projectone`.
- Android version code: `8`.
- Expo / app version: `1.4.0`.
- Session storage: Android Keystore through `expo-secure-store`.
- Authentication: existing Velora password endpoint with optional TOTP; opaque bearer session token.
- Company context: `X-Velora-Company`, validated by Velora on every business request.

No OIDC discovery URL, external client ID, client secret or external identity provider is configured.
