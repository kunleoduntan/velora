import { publicApi, api, saveAccessToken, clearAccessToken, clearActiveCompany, saveActiveCompany } from './api';

export type VeloraCompany = { id: string; name: string; tenant?: string; status?: string; roles?: string[] };
export type VeloraProfile = {
  user: { email: string; full_name: string; is_platform_admin: boolean };
  companies: VeloraCompany[];
  active_company: string | null;
  default_company: string | null;
};
type Envelope<T> = { data: T };

export async function login(email: string, password: string, totpCode?: string): Promise<VeloraProfile> {
  const result = await publicApi<Envelope<VeloraProfile & { token?: string }>>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email: email.trim(), password, totp_code: totpCode?.trim() || undefined, return_token: true }),
  });
  if (!result.data?.token) throw new Error('Velora did not return a mobile session token.');
  await saveAccessToken(result.data.token);
  const { token: _token, ...profile } = result.data;
  if (profile.active_company) await saveActiveCompany(profile.active_company);
  else await clearActiveCompany();
  return profile;
}

export async function restoreSession(): Promise<VeloraProfile> {
  const result = await api<Envelope<VeloraProfile>>('/api/auth/me');
  if (result.data.active_company) await saveActiveCompany(result.data.active_company);
  else await clearActiveCompany();
  return result.data;
}

export async function selectCompany(companyId: string): Promise<void> {
  await api<Envelope<{ id: string; name: string; roles: string[] }>>('/api/auth/switch-company', {
    method: 'POST', body: JSON.stringify({ company_id: companyId }),
  });
  await saveActiveCompany(companyId);
}

export async function logout(): Promise<void> {
  try { await api('/api/auth/logout', { method: 'POST' }); }
  finally { await clearAccessToken(); }
}
