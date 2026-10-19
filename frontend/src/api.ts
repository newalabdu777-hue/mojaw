/** Shared API transport for the starter UI. Access tokens stay in sessionStorage (tab-scoped). */
const TOKEN_KEY = 'school_access_token';

export function getAccessToken(): string | null {
  try { return window.sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setAccessToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  try { window.sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage may be unavailable */ }
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 && token) {
    clearAccessToken();
    window.dispatchEvent(new Event('school-auth-expired'));
  }
  return response;
}
