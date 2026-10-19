import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import { toMinorUnits } from './money.mjs';
import { apiFetch } from './api';

type Student = { student_id: string; given_name: string; middle_name: string | null; family_name: string; branch_id: string };
type Bill = { bill_id: string; student_id: string; description: string; amount_minor: number; paid_minor: number; outstanding_minor: number; currency: string; due_date: string | null; status: string };
type Payment = { payment_id: string; student_id: string; provisional_ref: string; amount_minor: number; currency: string; payment_method: string; status: string };
type LedgerAccount = { account_id: string; code: string; name: string; account_type: string; currency: string; status: string };
type TrialBalance = { items: Array<LedgerAccount & { debit_minor: number; credit_minor: number; net_debit_minor: number }>; total_debit_minor: number; total_credit_minor: number; is_balanced: boolean; currency: string };
type LedgerJournal = { journal_id: string; description: string; currency: string; status: string; created_at: string; reversal_of_id: string | null; reversed_by_id: string | null; total_debit_minor: number; total_credit_minor: number; lines: Array<{ line_number: number; account_id: string; account_code: string; account_name: string; debit_minor: number; credit_minor: number }> };
type Props = { isAm: boolean };

export default function FinancePage({ isAm }: Props) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const [students, setStudents] = useState<Student[]>([]);
  const [studentSearchInput, setStudentSearchInput] = useState('');
  const [studentSearch, setStudentSearch] = useState('');
  const [studentOffset, setStudentOffset] = useState(0);
  const [studentTotal, setStudentTotal] = useState(0);
  const studentPageSize = 50;
  const [bills, setBills] = useState<Bill[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [ledgerAccounts, setLedgerAccounts] = useState<LedgerAccount[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalance | null>(null);
  const [journals, setJournals] = useState<LedgerJournal[]>([]);
  const [journalOffset, setJournalOffset] = useState(0);
  const [journalTotal, setJournalTotal] = useState(0);
  const journalPageSize = 50;
  const [reversalReasons, setReversalReasons] = useState<Record<string, string>>({});
  const [accountCode, setAccountCode] = useState('1000');
  const [accountName, setAccountName] = useState('Cash');
  const [accountType, setAccountType] = useState('asset');
  const [debitAccountId, setDebitAccountId] = useState('');
  const [creditAccountId, setCreditAccountId] = useState('');
  const [journalDescription, setJournalDescription] = useState('Opening entry');
  const [journalAmount, setJournalAmount] = useState('1000');
  const [studentId, setStudentId] = useState('');
  const [description, setDescription] = useState('Tuition fee');
  const [billAmount, setBillAmount] = useState('1000');
  const [dueDate, setDueDate] = useState('');
  const [paymentAmount, setPaymentAmount] = useState('1000');
  const [allocationAmount, setAllocationAmount] = useState('1000');
  const [billId, setBillId] = useState('');
  const [method, setMethod] = useState('cash');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const loadRequestId = useRef(0);
  // A ref closes the same-tick double-submit window before React updates `saving`.
  const mutationInFlight = useRef(false);
  // Reuse the same key after an uncertain journal response so server retries stay idempotent.
  const journalIdempotencyKey = useRef<string | null>(null);
  const billIdempotencyKey = useRef<string | null>(null);
  const paymentIdempotencyKey = useRef<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const l = isAm ? {
    title: 'የትምህርት ክፍያና ሂሳብ', ledger: 'አጠቃላይ የሂሳብ መዝገብ', journalHistory: 'የግብይት ታሪክ', reverse: 'መልሶ መመዝገብ', reversalReason: 'የማስተካከያ ምክንያት', reversed: 'ተመልሶ ተመዝግቧል', reversal: 'የተመላሽ ግብይት', accounts: 'የሂሳብ አካውንቶች', addAccount: 'አካውንት ጨምር', code: 'ኮድ', name: 'ስም', type: 'ዓይነት', debitAccount: 'Debit አካውንት', creditAccount: 'Credit አካውንት', journal: 'የሂሳብ ግብይት መዝግብ', journalDescription: 'የግብይት መግለጫ', trialBalance: 'Trial Balance', debit: 'Debit', credit: 'Credit', total: 'ድምር', desc: 'የክፍያ ሂሳቦችን ይፍጠሩ፣ ክፍያዎችን ይመዝግቡና ያስታርቁ።', warning: 'የልማት ሙከራ ብቻ። እውነተኛ የተማሪ ወይም የገንዘብ ዳታ አይጠቀሙ።', student: 'ተማሪ', choose: 'ተማሪ ይምረጡ', description: 'የክፍያ ምክንያት', amount: 'መጠን (ብር)', due: 'የመክፈያ ቀን', createBill: 'የክፍያ ሂሳብ ፍጠር', bills: 'የክፍያ ዝርዝር', payment: 'ክፍያ መመዝገብ', method: 'የክፍያ ዘዴ', bill: 'ሂሳብ', allocate: 'ለሂሳቡ የሚመደብ (ብር)', record: 'ክፍያ መዝግብ', reconcile: 'አስታርቅ', payments: 'የክፍያ ታሪክ', original: 'የመጀመሪያ መጠን', paid: 'የተከፈለ', outstanding: 'ቀሪ', status: 'ሁኔታ', ref: 'ጊዜያዊ ማጣቀሻ', noBills: 'የክፍያ ሂሳብ የለም።', noPayments: 'ክፍያ አልተመዘገበም።', refresh: 'አድስ', loading: 'በመጫን ላይ…', saved: 'ተቀምጧል።', pending: 'ማስታረቅ ይጠብቃል', reconciled: 'ተስታርቋል', noStudent: 'መጀመሪያ ተማሪ ይመዝግቡ።', cash: 'ጥሬ ገንዘብ', bank: 'ባንክ ማስተላለፍ', mobile: 'ሞባይል ገንዘብ', card: 'ካርድ', other: 'ሌላ',
  } : {
    title: 'Fees & student accounts', ledger: 'General ledger', journalHistory: 'Journal history', reverse: 'Reverse journal', reversalReason: 'Reason for reversal', reversed: 'Reversed', reversal: 'Reversal entry', accounts: 'Chart of accounts', addAccount: 'Add account', code: 'Code', name: 'Name', type: 'Account type', debitAccount: 'Debit account', creditAccount: 'Credit account', journal: 'Post journal entry', journalDescription: 'Journal description', trialBalance: 'Trial balance', debit: 'Debit', credit: 'Credit', total: 'Total', desc: 'Create fee bills, record payments and reconcile provisional payments.', warning: 'Development prototype only. Never use real student or financial data.', student: 'Student', choose: 'Choose a student', description: 'Fee description', amount: 'Amount (ETB)', due: 'Due date', createBill: 'Create fee bill', bills: 'Fee bills', payment: 'Record payment', method: 'Payment method', bill: 'Bill to allocate to', allocate: 'Allocate to bill (ETB)', record: 'Record payment', reconcile: 'Reconcile', payments: 'Payment history', original: 'Original', paid: 'Paid', outstanding: 'Outstanding', status: 'Status', ref: 'Provisional reference', noBills: 'No fee bills yet.', noPayments: 'No payments yet.', refresh: 'Refresh', loading: 'Loading…', saved: 'Saved.', pending: 'Pending reconciliation', reconciled: 'Reconciled', noStudent: 'Register a student first.', cash: 'Cash', bank: 'Bank transfer', mobile: 'Mobile money', card: 'Card', other: 'Other',
  };
  const money = (minor: number, currency = 'ETB') => new Intl.NumberFormat(isAm ? 'am-ET' : 'en-ET', { style: 'currency', currency }).format(minor / 100);
  async function request(path: string, init?: RequestInit): Promise<unknown> {
    const response = await apiFetch(`${apiBase}${path}`, { ...init, headers: { 'X-Organization-ID': orgId, ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) } });
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    if (!response.ok) throw new Error(body?.detail || `API returned ${response.status}`);
    return body;
  }
  async function load() {
    const requestId = ++loadRequestId.current;
    setLoading(true); setError('');
    try {
      const [s, b, p, a, tb, journalResponse] = await Promise.all([
        request(`/api/v1/students?limit=${studentPageSize}&offset=${studentOffset}${studentSearch.trim() ? `&q=${encodeURIComponent(studentSearch.trim())}` : ''}`),
        // Never load every student's financial records when no student is selected.
        studentId ? request(`/api/v1/finance/bills?student_id=${encodeURIComponent(studentId)}`) : Promise.resolve({ items: [] }),
        studentId ? request(`/api/v1/finance/payments?student_id=${encodeURIComponent(studentId)}`) : Promise.resolve({ items: [] }),
        request('/api/v1/finance/ledger/accounts'),
        request('/api/v1/finance/ledger/trial-balance?currency=ETB'),
        request(`/api/v1/finance/ledger/journals?currency=ETB&limit=${journalPageSize}&offset=${journalOffset}`),
      ]);
      // A later search/page refresh wins; ignore stale responses from earlier requests.
      if (requestId !== loadRequestId.current) return;
      const studentPage = s as { items: Student[]; total: number };
      const nextStudents = studentPage.items;
      setStudents(nextStudents);
      setStudentTotal(studentPage.total);
      // Never select a student implicitly on a financial screen; require an explicit user choice.
      setBills((b as { items: Bill[] }).items);
      setPayments((p as { items: Payment[] }).items);
      const nextAccounts = (a as { items: LedgerAccount[] }).items;
      setLedgerAccounts(nextAccounts);
      setTrialBalance(tb as TrialBalance);
      const journalPage = journalResponse as { items: LedgerJournal[]; total: number };
      setJournals(journalPage.items);
      setJournalTotal(journalPage.total);
      if (nextAccounts.length) {
        setDebitAccountId(current => current && nextAccounts.some(account => account.account_id === current) ? current : nextAccounts[0].account_id);
        setCreditAccountId(current => current && nextAccounts.some(account => account.account_id === current) ? current : (nextAccounts.find(account => account.account_id !== nextAccounts[0].account_id)?.account_id || ''));
      }
    } catch (e) {
      if (requestId === loadRequestId.current) setError(e instanceof Error ? e.message : 'API error');
    } finally {
      if (requestId === loadRequestId.current) setLoading(false);
    }
  }
  useEffect(() => { void load(); }, [apiBase, orgId, studentId, journalOffset, studentSearch, studentOffset]);
  useEffect(() => {
    // Never retain a bill selection that belongs to a different student or has no balance.
    const selectedBill = bills.find(b => b.bill_id === billId && b.outstanding_minor > 0);
    const nextBillId = selectedBill?.bill_id || bills.find(b => b.outstanding_minor > 0)?.bill_id || '';
    if (nextBillId !== billId) setBillId(nextBillId);
  }, [bills, billId]);
  async function createBill(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (!studentId || mutationInFlight.current) return; mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    if (!billIdempotencyKey.current) billIdempotencyKey.current = crypto.randomUUID();
    try {
      await request('/api/v1/finance/bills', { method: 'POST', headers: { 'Idempotency-Key': billIdempotencyKey.current }, body: JSON.stringify({ student_id: studentId, description, amount_minor: toMinorUnits(billAmount), currency: 'ETB', due_date: dueDate || null }) });
      billIdempotencyKey.current = null; setNotice(l.saved); await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  async function createPayment(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (!studentId || mutationInFlight.current) return; mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    if (!paymentIdempotencyKey.current) paymentIdempotencyKey.current = crypto.randomUUID();
    try {
      const amountMinor = toMinorUnits(paymentAmount);
      const allocationMinor = toMinorUnits(allocationAmount, true);
      if (allocationMinor > amountMinor) throw new Error(isAm ? 'ለሂሳቡ የሚመደበው መጠን ከክፍያው መብለጥ አይችልም።' : 'Allocation cannot exceed the payment amount.');
      await request('/api/v1/finance/payments', { method: 'POST', headers: { 'Idempotency-Key': paymentIdempotencyKey.current }, body: JSON.stringify({ student_id: studentId, amount_minor: amountMinor, currency: 'ETB', payment_method: method, allocations: billId && allocationMinor > 0 ? [{ bill_id: billId, amount_minor: allocationMinor }] : [] }) });
      paymentIdempotencyKey.current = null; setNotice(l.saved); await load();
    }
    catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  async function reconcile(id: string) {
    if (mutationInFlight.current) return; mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    try { await request(`/api/v1/finance/payments/${encodeURIComponent(id)}/reconcile`, { method: 'POST' }); setNotice(l.saved); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  async function createLedgerAccount(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (mutationInFlight.current) return; mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    try { await request('/api/v1/finance/ledger/accounts', { method: 'POST', body: JSON.stringify({ code: accountCode, name: accountName, account_type: accountType, currency: 'ETB' }) }); setNotice(l.saved); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  async function postJournal(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (mutationInFlight.current) return; if (!debitAccountId || !creditAccountId || debitAccountId === creditAccountId) { setError(isAm ? 'ሁለት የተለያዩ አካውንቶችን ይምረጡ።' : 'Choose two different accounts.'); return; }
    mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    if (!journalIdempotencyKey.current) journalIdempotencyKey.current = crypto.randomUUID();
    try { await request('/api/v1/finance/ledger/journals', { method: 'POST', headers: { 'Idempotency-Key': journalIdempotencyKey.current }, body: JSON.stringify({ description: journalDescription, currency: 'ETB', lines: [{ account_id: debitAccountId, debit_minor: toMinorUnits(journalAmount), credit_minor: 0 }, { account_id: creditAccountId, debit_minor: 0, credit_minor: toMinorUnits(journalAmount) }] }) }); journalIdempotencyKey.current = null; setJournalOffset(0); setNotice(l.saved); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  async function reverseJournal(journalId: string) {
    const reason = (reversalReasons[journalId] || '').trim();
    if (reason.length < 3) { setError(isAm ? 'ምክንያቱ ቢያንስ 3 ቁምፊ መሆን አለበት።' : 'Enter a reason of at least 3 characters.'); return; }
    if (!window.confirm(isAm ? 'ይህን ግብይት በተቃራኒ መዝገብ መመለስ ይፈልጋሉ?' : 'Post an exact reversing entry? The original journal will remain unchanged.')) return;
    if (mutationInFlight.current) return; mutationInFlight.current = true; setSaving(true); setError(''); setNotice('');
    try {
      await request(`/api/v1/finance/ledger/journals/${encodeURIComponent(journalId)}/reverse`, { method: 'POST', body: JSON.stringify({ reason }) });
      setReversalReasons(old => ({ ...old, [journalId]: '' }));
      setJournalOffset(0);
      setNotice(isAm ? 'የተመላሽ ግብይቱ ተመዝግቧል።' : 'Reversal journal posted. The original entry remains immutable.');
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'API error'); } finally { mutationInFlight.current = false; setSaving(false); }
  }
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">FINANCE</div><h1>{l.title}</h1><p>{l.desc}</p></div><div className="directory-actions"><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} /> {l.refresh}</button></div></div>
    <div className="prototype-alert"><ShieldCheck size={18} /><span>{l.warning} <strong>Official receipt numbers are not issued by this prototype.</strong></span></div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status">{notice}</div>}
    <div className="student-form"><form className="student-form-grid" onSubmit={e => { e.preventDefault(); setStudentOffset(0); setStudentId(''); setStudentSearch(studentSearchInput.trim()); }}><label className="full-field">{isAm ? 'ተማሪ ፈልግ' : 'Search students'}<input value={studentSearchInput} onChange={e => setStudentSearchInput(e.target.value)} placeholder={isAm ? 'ስም ወይም የተማሪ ቁጥር' : 'Name or student number'} /></label><div className="form-actions"><button type="submit" className="secondary-button">{isAm ? 'ፈልግ' : 'Search'}</button><span className="muted-small">{studentTotal} {isAm ? 'ተማሪዎች' : 'students'}</span></div></form><div className="student-form-grid"><label className="full-field">{l.student}<select value={studentId} onChange={e => { const nextStudentId = e.target.value; setStudentId(nextStudentId); setBills([]); setPayments([]); setBillId(''); }}><option value="">{l.choose}</option>{students.map(s => <option key={s.student_id} value={s.student_id}>{s.given_name} {s.middle_name || ''} {s.family_name} · {s.branch_id}</option>)}</select></label></div><div className="form-actions"><span className="muted-small">{studentTotal ? `${studentOffset + 1}–${Math.min(studentOffset + students.length, studentTotal)} / ${studentTotal}` : '0 / 0'}</span><button type="button" className="secondary-button" disabled={loading || studentOffset === 0} onClick={() => { setStudentId(''); setStudentOffset(offset => Math.max(0, offset - studentPageSize)); }}>{isAm ? 'ቀዳሚ' : 'Previous'}</button><button type="button" className="secondary-button" disabled={loading || studentOffset + studentPageSize >= studentTotal} onClick={() => { setStudentId(''); setStudentOffset(offset => offset + studentPageSize); }}>{isAm ? 'ቀጣይ' : 'Next'}</button></div>{!studentTotal && <p className="table-message">{l.noStudent}</p>}</div>
    <div className="finance-form-grid">
      <form className="student-form" onSubmit={e => void createBill(e)}><h2>{l.createBill}</h2><div className="student-form-grid"><label className="full-field">{l.description}<input required maxLength={200} value={description} onChange={e => setDescription(e.target.value)} /></label><label>{l.amount}<input type="number" required min="0.01" step="0.01" value={billAmount} onChange={e => setBillAmount(e.target.value)} /></label><label>{l.due}<input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving || !studentId}><Plus size={15} /> {l.createBill}</button></div></form>
      <form className="student-form" onSubmit={e => void createPayment(e)}><h2>{l.payment}</h2><div className="student-form-grid"><label>{l.amount}<input type="number" required min="0.01" step="0.01" value={paymentAmount} onChange={e => setPaymentAmount(e.target.value)} /></label><label>{l.method}<select value={method} onChange={e => setMethod(e.target.value)}><option value="cash">{l.cash}</option><option value="bank_transfer">{l.bank}</option><option value="mobile_money">{l.mobile}</option><option value="card">{l.card}</option><option value="other">{l.other}</option></select></label><label className="full-field">{l.bill}<select value={billId} onChange={e => setBillId(e.target.value)}><option value="">—</option>{bills.filter(b => b.outstanding_minor > 0).map(b => <option key={b.bill_id} value={b.bill_id}>{b.description} · {money(b.outstanding_minor)}</option>)}</select></label><label className="full-field">{l.allocate}<input type="number" required min="0" step="0.01" value={allocationAmount} onChange={e => setAllocationAmount(e.target.value)} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving || !studentId}><Plus size={15} /> {l.record}</button></div></form>
    </div>
    <div className="student-form"><div className="directory-toolbar"><span>{l.bills}</span><strong>{bills.length}</strong></div><div className="student-table-wrap"><table className="student-table"><thead><tr><th>{l.description}</th><th>{l.original}</th><th>{l.paid}</th><th>{l.outstanding}</th><th>{l.due}</th><th>{l.status}</th></tr></thead><tbody>{loading ? <tr><td colSpan={6} className="table-message">{l.loading}</td></tr> : !bills.length ? <tr><td colSpan={6} className="table-message">{l.noBills}</td></tr> : bills.map(b => <tr key={b.bill_id}><td><strong>{b.description}</strong></td><td>{money(b.amount_minor, b.currency)}</td><td>{money(b.paid_minor, b.currency)}</td><td>{money(b.outstanding_minor, b.currency)}</td><td>{b.due_date || '—'}</td><td><span className="student-status">{b.status}</span></td></tr>)}</tbody></table></div></div>
    <div className="student-form"><div className="directory-toolbar"><span>{l.payments}</span><strong>{payments.length}</strong></div><div className="student-table-wrap"><table className="student-table"><thead><tr><th>{l.ref}</th><th>{l.amount}</th><th>{l.method}</th><th>{l.status}</th><th>{l.reconcile}</th></tr></thead><tbody>{loading ? <tr><td colSpan={5} className="table-message">{l.loading}</td></tr> : !payments.length ? <tr><td colSpan={5} className="table-message">{l.noPayments}</td></tr> : payments.map(p => <tr key={p.payment_id}><td><strong>{p.provisional_ref}</strong></td><td>{money(p.amount_minor, p.currency)}</td><td>{p.payment_method}</td><td><span className="student-status">{p.status === 'reconciled' ? l.reconciled : l.pending}</span></td><td>{p.status === 'pending_reconciliation' ? <button className="secondary-button" disabled={saving} onClick={() => void reconcile(p.payment_id)}>{l.reconcile}</button> : '—'}</td></tr>)}</tbody></table></div></div>
    <div className="directory-heading"><div><div className="eyebrow">GENERAL LEDGER</div><h1>{l.ledger}</h1></div></div>
    <div className="finance-form-grid">
      <form className="student-form" onSubmit={e => void createLedgerAccount(e)}><h2>{l.addAccount}</h2><div className="student-form-grid"><label>{l.code}<input required maxLength={20} value={accountCode} onChange={e => setAccountCode(e.target.value)} /></label><label>{l.name}<input required maxLength={120} value={accountName} onChange={e => setAccountName(e.target.value)} /></label><label className="full-field">{l.type}<select value={accountType} onChange={e => setAccountType(e.target.value)}><option value="asset">Asset</option><option value="liability">Liability</option><option value="equity">Equity</option><option value="revenue">Revenue</option><option value="expense">Expense</option></select></label></div><div className="form-actions"><button className="primary-button" disabled={saving}><Plus size={15} /> {l.addAccount}</button></div></form>
      <form className="student-form" onSubmit={e => void postJournal(e)}><h2>{l.journal}</h2><div className="student-form-grid"><label className="full-field">{l.journalDescription}<input required maxLength={240} value={journalDescription} onChange={e => setJournalDescription(e.target.value)} /></label><label className="full-field">{l.debitAccount}<select required value={debitAccountId} onChange={e => setDebitAccountId(e.target.value)}><option value="">—</option>{ledgerAccounts.filter(a => a.status === 'active' && a.currency === 'ETB').map(a => <option key={a.account_id} value={a.account_id}>{a.code} · {a.name}</option>)}</select></label><label className="full-field">{l.creditAccount}<select required value={creditAccountId} onChange={e => setCreditAccountId(e.target.value)}><option value="">—</option>{ledgerAccounts.filter(a => a.status === 'active' && a.currency === 'ETB').map(a => <option key={a.account_id} value={a.account_id}>{a.code} · {a.name}</option>)}</select></label><label className="full-field">{l.amount}<input type="number" required min="0.01" step="0.01" value={journalAmount} onChange={e => setJournalAmount(e.target.value)} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving || ledgerAccounts.length < 2}><Plus size={15} /> {l.journal}</button></div></form>
    </div>
    <div className="student-form"><div className="directory-toolbar"><span>{l.journalHistory}</span><strong>{journalTotal}</strong></div><div className="student-table-wrap"><table className="student-table"><thead><tr><th>{l.journalDescription}</th><th>{l.debit}</th><th>{l.credit}</th><th>{l.status}</th><th>{l.reversalReason}</th><th>{l.reverse}</th></tr></thead><tbody>{loading ? <tr><td colSpan={6} className="table-message">{l.loading}</td></tr> : !journals.length ? <tr><td colSpan={6} className="table-message">{isAm ? 'የግብይት ታሪክ የለም።' : 'No journal entries yet.'}</td></tr> : journals.map(j => <tr key={j.journal_id}><td><strong>{j.description}</strong><div className="muted-small">{j.journal_id.slice(0, 8)} · {j.created_at}</div>{j.reversal_of_id && <span className="student-status">{l.reversal}</span>}</td><td>{money(j.total_debit_minor, j.currency)}</td><td>{money(j.total_credit_minor, j.currency)}</td><td><span className="student-status">{j.reversed_by_id ? l.reversed : j.status}</span></td><td>{!j.reversal_of_id && !j.reversed_by_id ? <input aria-label={`${l.reversalReason} ${j.journal_id}`} maxLength={240} value={reversalReasons[j.journal_id] || ''} onChange={e => setReversalReasons(old => ({ ...old, [j.journal_id]: e.target.value }))} placeholder={l.reversalReason} /> : (j.reversal_of_id ? j.description : '—')}</td><td>{!j.reversal_of_id && !j.reversed_by_id ? <button className="secondary-button" disabled={saving || (reversalReasons[j.journal_id] || '').trim().length < 3} onClick={() => void reverseJournal(j.journal_id)}>{l.reverse}</button> : '—'}</td></tr>)}</tbody></table></div><div className="form-actions journal-pagination"><span className="muted-small">{journalTotal ? `${journalOffset + 1}–${Math.min(journalOffset + journals.length, journalTotal)} / ${journalTotal}` : '0 / 0'}</span><button type="button" className="secondary-button" disabled={loading || journalOffset === 0} onClick={() => setJournalOffset(offset => Math.max(0, offset - journalPageSize))}>{isAm ? 'ቀዳሚ' : 'Previous'}</button><button type="button" className="secondary-button" disabled={loading || journalOffset + journalPageSize >= journalTotal} onClick={() => setJournalOffset(offset => offset + journalPageSize)}>{isAm ? 'ቀጣይ' : 'Next'}</button></div></div>
    <div className="student-form"><div className="directory-toolbar"><span>{l.trialBalance} · ETB</span><strong>{trialBalance?.is_balanced ? 'Balanced' : 'Not balanced'}</strong></div><div className="student-table-wrap"><table className="student-table"><thead><tr><th>{l.code}</th><th>{l.name}</th><th>{l.type}</th><th>{l.debit}</th><th>{l.credit}</th></tr></thead><tbody>{loading ? <tr><td colSpan={5} className="table-message">{l.loading}</td></tr> : !trialBalance?.items.length ? <tr><td colSpan={5} className="table-message">{isAm ? 'የሂሳብ መዝገብ አልተፈጠረም።' : 'No ledger accounts yet.'}</td></tr> : trialBalance.items.map(a => <tr key={a.account_id}><td>{a.code}</td><td><strong>{a.name}</strong></td><td>{a.account_type}</td><td>{money(a.debit_minor, trialBalance.currency)}</td><td>{money(a.credit_minor, trialBalance.currency)}</td></tr>)}</tbody><tfoot><tr><th colSpan={3}>{l.total}</th><th>{money(trialBalance?.total_debit_minor || 0, trialBalance?.currency || 'ETB')}</th><th>{money(trialBalance?.total_credit_minor || 0, trialBalance?.currency || 'ETB')}</th></tr></tfoot></table></div></div>
  </section>;
}
