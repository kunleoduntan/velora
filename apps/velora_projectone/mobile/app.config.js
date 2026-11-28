/**
 * Public build-time configuration for Velora ProjectOne Mobile.
 * The API default is the address supplied for this deployment. Override it
 * through EXPO_PUBLIC_PROJECTONE_API_BASE for dev, staging or production.
 */
const { resolvePublicConfig } = require('./scripts/public-config.cjs');

module.exports = ({ config }) => {
  const publicConfig = resolvePublicConfig(process.env);

  return {
    ...config,
    name: 'Velora ProjectOne',
    slug: 'velora-projectone-mobile',
    version: '1.4.0',
    scheme: 'veloraprojectone',
    orientation: 'portrait',
    userInterfaceStyle: 'automatic',
    newArchEnabled: true,
    ios: {
      ...config.ios,
      supportsTablet: true,
      bundleIdentifier: 'com.velora.projectone',
      buildNumber: '8',
    },
    android: {
      ...config.android,
      package: 'com.velora.projectone',
      permissions: [],
      versionCode: 8,
    },
    plugins: ['expo-secure-store'],
    extra: {
      ...config.extra,
      ...publicConfig,
      ...(process.env.EXPO_PROJECT_ID ? { eas: { ...(config.extra?.eas || {}), projectId: process.env.EXPO_PROJECT_ID } } : {}),
    },
  };
};
