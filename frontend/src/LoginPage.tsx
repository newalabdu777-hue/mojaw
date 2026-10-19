import { useState, type FormEvent } from 'react';
import { GraduationCap, ShieldCheck } from 'lucide-react';
import { setAccessToken } from './api';

type Props = { isAm: boolean; onLogin: () => void };
type LoginResponse = { access_token?: string; user?: { email?: string; role?: string }; detail?: string };

export default function LoginPage({ isAm, onLogin }: Props) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const defaultOrg = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const [organizationId, setOrganizationId] = useState(defaultOrg);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ organization_id: organizationId.trim(), email: email.trim(), password }),
      });
      const body = await response.json().catch(() => null) as LoginResponse | null;
      if (!response.ok || !body?.access_token) throw new Error(body?.detail || (isAm ? 'መግባት አልተቻለም።' : 'Sign-in failed. Check your credentials and organization ID.'));
      setAccessToken(body.access_token); setPassword(''); onLogin();
    } catch (e) { setError(e instanceof Error ? e.message : (isAm ? 'የኔትወርክ ስህተት።' : 'Network error. Check that the API is running.')); }
    finally { setBusy(false); }
  }
  return <main className="login-shell"><form className="login-card" onSubmit={submit}>
    <div className="login-brand"><span className="login-mark"><GraduationCap size={28} /></span><div><h1>{isAm ? 'የትምህርት ቤት ስርዓት' : 'School Management'}</h1><p>{isAm ? 'ወደ ድርጅትዎ መለያ ይግቡ' : 'Sign in to your organization'}</p></div></div>
    <div className="login-security"><ShieldCheck size={16} /> {isAm ? 'የተጠበቀ መግቢያ · የልማት ሙከራ' : 'Authenticated access · Development prototype'}</div>
    <label>{isAm ? 'የድርጅት መለያ' : 'Organization ID'}<input required maxLength={64} autoComplete="organization" value={organizationId} onChange={e => setOrganizationId(e.target.value)} /></label>
    <label>{isAm ? 'ኢሜይል' : 'Email address'}<input required type="email" autoComplete="username" maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
    <label>{isAm ? 'የይለፍ ቃል' : 'Password'}<input required type="password" autoComplete="current-password" maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
    {error && <div className="login-error" role="alert">{error}</div>}
    <button className="primary-button login-submit" disabled={busy}>{busy ? (isAm ? 'በመግባት ላይ…' : 'Signing in…') : (isAm ? 'ግባ' : 'Sign in')}</button>
    <p className="login-footnote">{isAm ? 'የመጀመሪያ አስተዳዳሪው በAPI bootstrap መንገድ መፈጠር አለበት።' : 'The first administrator must be created using the protected API bootstrap endpoint.'}</p>
  </form></main>;
}
