import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string>;
export const API_BASE = (extra.projectOneApiBase || '').replace(/\/$/, '');
const TOKEN_KEY = 'velora.session_token';
const COMPANY_KEY = 'velora.active_company';
let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) { unauthorizedHandler = handler; }

export async function saveAccessToken(token: string) {
  await SecureStore.setItemAsync(TOKEN_KEY, token, { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK });
}
export async function clearAccessToken() { await SecureStore.deleteItemAsync(TOKEN_KEY); await clearActiveCompany(); }
export async function getAccessToken() { return SecureStore.getItemAsync(TOKEN_KEY); }
export async function saveActiveCompany(companyId: string) { await SecureStore.setItemAsync(COMPANY_KEY, companyId); }
export async function clearActiveCompany() { await SecureStore.deleteItemAsync(COMPANY_KEY); }
export async function getActiveCompany() { return SecureStore.getItemAsync(COMPANY_KEY); }

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

async function decodeResponse<T>(response: Response): Promise<T> {
  const raw = await response.text();
  let payload: any = {};
  try { payload = raw ? JSON.parse(raw) : {}; } catch { payload = { message: raw }; }
  if (!response.ok) {
    if (response.status === 401) { await clearAccessToken(); unauthorizedHandler?.(); }
    throw new ApiError(payload.detail || payload.message || `Request failed (${response.status})`, response.status);
  }
  return payload as T;
}

export async function publicApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!API_BASE || !API_BASE.startsWith('https://')) throw new Error('Configure a valid HTTPS projectOneApiBase before connecting.');
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetch(`${API_BASE}${path}`, { ...options, headers }); }
  catch { throw new Error('Unable to reach Velora. Check your connection and server address.'); }
  return decodeResponse<T>(response);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!API_BASE || !API_BASE.startsWith('https://')) throw new Error('Configure a valid HTTPS projectOneApiBase before connecting.');
  const token = await getAccessToken();
  if (!token) throw new Error('Your session has expired. Sign in again.');
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${token}`);
  headers.set('Accept', 'application/json');
  const companyId = await getActiveCompany();
  if (companyId) headers.set('X-Velora-Company', companyId);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetch(`${API_BASE}${path}`, { ...options, headers }); }
  catch { throw new Error('Unable to reach Velora. Check your connection and server address.'); }
  return decodeResponse<T>(response);
}

/** Velora answers every call as { data: ... }; the screens work with the inner value. */
const body = async <T>(path: string, options: RequestInit = {}): Promise<T> => (await api<{ data: T }>(path, options)).data;

export const routes = {
  projects: () => body<any[]>('/api/projectone/native/documents/Project?limit=100&offset=0'),
  executive: () => body<any>('/api/projectone/portfolio/executive-workspace'),
  approvals: () => body<any[]>('/api/projectone/native/workflow-inbox?limit=100'),
  workbench: (projectId: string) => body<any>(`/api/projectone/workbench/projects/${encodeURIComponent(projectId)}`),
  comment: (taskId: string, comment: string) => body<any>(`/api/projectone/tasks/${encodeURIComponent(taskId)}/comments`, { method: 'POST', body: JSON.stringify({ comment }) }),
  integration: () => body<any>('/api/projectone/integrations/readiness'),
  health: () => body<any>('/api/projectone/health'),
  workflow: (doctype: string, name: string, action: string, evidence?: string) => body<any>(`/api/projectone/native/workflow/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}/${encodeURIComponent(action)}`, { method: 'POST', body: JSON.stringify(evidence ? { evidence } : {}) }),
};
