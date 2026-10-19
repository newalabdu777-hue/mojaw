import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import FinancePage from './FinancePage';
import LoginPage from './LoginPage';
import { apiFetch, clearAccessToken } from './api';
import { createMutationEnvelope, enqueueMutation, listOutboxMutations } from './offlineOutbox.mjs';
import { mergePendingAssessmentResults } from './assessmentOffline.mjs';
import { readSnapshot, saveSnapshot } from './offlineSnapshots.mjs';
import SyncPanel from './SyncPanel';
import {
  Activity, ArrowDownRight, ArrowUpRight, BookOpen, CalendarCheck, ChartNoAxesCombined,
  CheckCircle2, ChevronDown, CircleDollarSign, ClipboardList, CloudOff, GraduationCap,
  Languages, LayoutDashboard, Menu, Search, Settings, ShieldCheck, Users, Plus, RefreshCw, Download, Printer,
} from 'lucide-react';

type Lang = 'en' | 'am';
type Page = 'dashboard' | 'students' | 'classrooms' | 'attendance' | 'academics' | 'finance' | 'reports' | 'settings';

const copy = {
  en: {
    school: 'Aster School', branch: 'Main Branch', overview: 'Overview', dashboard: 'Dashboard', students: 'Students', classrooms: 'Classes & enrollment', attendance: 'Attendance', academics: 'Academics', finance: 'Fees & Finance', reports: 'Reports', settings: 'Settings',
    welcome: 'Good morning, Administrator', subtitle: 'Here is what is happening at your school today.', totalStudents: 'Total students', presentToday: 'Present today', feeCollection: 'Fee collection', pendingFees: 'Pending fees', fromLastMonth: 'from last month', attendanceRate: 'attendance rate', collectedThisMonth: 'collected this month', outstandingBalance: 'outstanding balance', weeklyAttendance: 'Weekly attendance', recentActivity: 'Recent activity', viewAll: 'View all', quickActions: 'Quick actions', addStudent: 'Add student', recordAttendance: 'Record attendance', enterMarks: 'Enter marks', recordPayment: 'Record payment', syncStatus: 'Sync status', offlineReady: 'Sync not configured', lastSync: 'Offline sync is not implemented', demo: 'Demo data', search: 'Search students, classes, records…', notifications: 'Notifications', admin: 'School administrator', online: 'Connected', offline: 'Offline mode', days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], activity: ['New student registered', 'Grade 8 attendance submitted', 'Fee payment recorded', 'Term 1 results updated'], ago: ['12 min ago', '38 min ago', '1 hour ago', '2 hours ago'], pageIntro: 'This module is represented in the starter interface. Connect the approved schema and API before using real school data.', moduleReady: 'Module preview', studentsTitle: 'Student directory', studentDesc: 'Manage student records, enrollment and guardian relationships.', studentSearch: 'Search by name or reference', firstName: 'Given name', middleName: 'Middle name (optional)', familyName: 'Family name', branchId: 'Branch ID', birthDate: 'Date of birth', sex: 'Sex at registration', female: 'Female', male: 'Male', unspecified: 'Unspecified', externalRef: 'External reference (optional)', createStudent: 'Register student', loading: 'Loading students…', noStudents: 'No students found.', apiError: 'Could not connect to the API. Start the backend and try again.', saved: 'Student registered in development storage.', reload: 'Refresh', totalRecords: 'records', prototypeWarning: 'Development prototype only. Do not enter real student information.', classroomsTitle: 'Classes & enrollment', classroomsDesc: 'Set up academic years, grade levels, sections and student enrollment.', attendanceTitle: 'Attendance', attendanceDesc: 'Track daily attendance and review corrections.', academicsTitle: 'Academic management', academicsDesc: 'Manage classes, assessments, marks and result publication.', financeTitle: 'Fees & finance', financeDesc: 'Bills, payments, student credit, receipts and reconciliation.', reportsTitle: 'Reports', reportsDesc: 'Academic and financial reports with explicit reporting cutoffs.', settingsTitle: 'System settings', settingsDesc: 'Organization, branches, languages, academic year and configuration versions.', demoNotice: 'Preview only — these figures are sample data and are not connected to a database.', chooseModule: 'Choose a module from the left navigation.',
  },
  am: {
    school: 'አስቴር ትምህርት ቤት', branch: 'ዋና ቅርንጫፍ', overview: 'አጠቃላይ እይታ', dashboard: 'ዳሽቦርድ', students: 'ተማሪዎች', classrooms: 'ክፍሎችና ምዝገባ', attendance: 'አቴንዳንስ', academics: 'ትምህርት', finance: 'ክፍያና ፋይናንስ', reports: 'ሪፖርቶች', settings: 'ቅንብሮች',
    welcome: 'እንደምን አደሩ፣ አስተዳዳሪ', subtitle: 'ዛሬ በትምህርት ቤትዎ የሚከናወኑ ነገሮች እነሆ።', totalStudents: 'ጠቅላላ ተማሪዎች', presentToday: 'ዛሬ የተገኙ', feeCollection: 'የተሰበሰበ ክፍያ', pendingFees: 'ያልተከፈለ ክፍያ', fromLastMonth: 'ካለፈው ወር', attendanceRate: 'የመገኘት መጠን', collectedThisMonth: 'በዚህ ወር የተሰበሰበ', outstandingBalance: 'ቀሪ ሂሳብ', weeklyAttendance: 'የሳምንቱ መገኘት', recentActivity: 'የቅርብ እንቅስቃሴዎች', viewAll: 'ሁሉንም ይመልከቱ', quickActions: 'ፈጣን እርምጃዎች', addStudent: 'ተማሪ ይጨምሩ', recordAttendance: 'መገኘት ይመዝግቡ', enterMarks: 'ውጤት ያስገቡ', recordPayment: 'ክፍያ ይመዝግቡ', syncStatus: 'የማመሳሰል ሁኔታ', offlineReady: 'ማመሳሰል አልተዋቀረም', lastSync: 'ኦፍላይን ማመሳሰል ገና አልተሠራም', demo: 'የሙከራ ዳታ', search: 'ተማሪ፣ ክፍል፣ መዝገብ ይፈልጉ…', notifications: 'ማሳወቂያዎች', admin: 'የትምህርት ቤት አስተዳዳሪ', online: 'ተገናኝቷል', offline: 'ኦፍላይን ሁኔታ', days: ['ሰኞ', 'ማክሰኞ', 'ረቡዕ', 'ሐሙስ', 'ዓርብ', 'ቅዳሜ', 'እሁድ'], activity: ['አዲስ ተማሪ ተመዝግቧል', 'የ8ኛ ክፍል መገኘት ተልኳል', 'የክፍያ መዝገብ ተደርጓል', 'የ1ኛ ሴሚስተር ውጤት ተዘምኗል'], ago: ['ከ12 ደቂቃ በፊት', 'ከ38 ደቂቃ በፊት', 'ከ1 ሰዓት በፊት', 'ከ2 ሰዓት በፊት'], pageIntro: 'ይህ ሞጁል በመሠረታዊ ገጽታ ውስጥ ተወክሏል። እውነተኛ የትምህርት ቤት ዳታ ከመጠቀምዎ በፊት የጸደቀውን ስኪማና API ያገናኙ።', moduleReady: 'የሞጁል ቅድመ እይታ', studentsTitle: 'የተማሪ መዝገብ', studentDesc: 'የተማሪ መረጃ፣ ምዝገባና የወላጅ ግንኙነት ያስተዳድሩ።', studentSearch: 'በስም ወይም በመለያ ይፈልጉ', firstName: 'ስም', middleName: 'የአባት ስም (አማራጭ)', familyName: 'የአያት ስም', branchId: 'የቅርንጫፍ መለያ', birthDate: 'የትውልድ ቀን', sex: 'በምዝገባ ጊዜ ጾታ', female: 'ሴት', male: 'ወንድ', unspecified: 'አልተገለጸም', externalRef: 'ውጫዊ መለያ (አማራጭ)', createStudent: 'ተማሪ ይመዝግቡ', loading: 'ተማሪዎች እየተጫኑ ነው…', noStudents: 'ተማሪ አልተገኘም።', apiError: 'ከAPI ጋር መገናኘት አልተቻለም። Backend ያስነሱና እንደገና ይሞክሩ።', saved: 'ተማሪው በልማት ዳታቤዝ ተመዝግቧል።', reload: 'እንደገና ጫን', totalRecords: 'መዝገቦች', prototypeWarning: 'የልማት ሙከራ ብቻ ነው። እውነተኛ የተማሪ መረጃ አያስገቡ።', classroomsTitle: 'ክፍሎችና የተማሪ ምዝገባ', classroomsDesc: 'የትምህርት ዓመት፣ ክፍል፣ ሴክሽንና የተማሪ ምዝገባ ያስተዳድሩ።', attendanceTitle: 'መገኘት', attendanceDesc: 'ዕለታዊ መገኘትን ይመዝግቡና ማስተካከያዎችን ይመልከቱ።', academicsTitle: 'የትምህርት አስተዳደር', academicsDesc: 'ክፍሎችን፣ ፈተናዎችን፣ ውጤቶችንና የውጤት ህትመትን ያስተዳድሩ።', financeTitle: 'ክፍያና ፋይናንስ', financeDesc: 'ደረሰኞች፣ ክፍያዎች፣ የተማሪ ክሬዲትና ማስታረቅ።', reportsTitle: 'ሪፖርቶች', reportsDesc: 'የትምህርትና የፋይናንስ ሪፖርቶች።', settingsTitle: 'የሲስተም ቅንብሮች', settingsDesc: 'ድርጅት፣ ቅርንጫፎች፣ ቋንቋ፣ የትምህርት ዓመትና የቅንብር ስሪቶች።', demoNotice: 'የቅድመ እይታ ብቻ — እነዚህ ቁጥሮች የሙከራ ዳታ ናቸው፣ ከዳታቤዝ ጋር አልተገናኙም።', chooseModule: 'ከግራ ያለው ምናሌ ሞጁል ይምረጡ።',
  },
};

const nav: { id: Page; icon: typeof LayoutDashboard }[] = [
  { id: 'dashboard', icon: LayoutDashboard }, { id: 'students', icon: Users }, { id: 'classrooms', icon: GraduationCap }, { id: 'attendance', icon: CalendarCheck },
  { id: 'academics', icon: BookOpen }, { id: 'finance', icon: CircleDollarSign }, { id: 'reports', icon: ChartNoAxesCombined }, { id: 'settings', icon: Settings },
];
const pageTitleKey: Record<Exclude<Page, 'dashboard'>, 'studentsTitle' | 'classroomsTitle' | 'attendanceTitle' | 'academicsTitle' | 'financeTitle' | 'reportsTitle' | 'settingsTitle'> = {
  students: 'studentsTitle', classrooms: 'classroomsTitle', attendance: 'attendanceTitle', academics: 'academicsTitle', finance: 'financeTitle', reports: 'reportsTitle', settings: 'settingsTitle',
};
const pageDescKey: Record<Exclude<Page, 'dashboard'>, 'studentDesc' | 'classroomsDesc' | 'attendanceDesc' | 'academicsDesc' | 'financeDesc' | 'reportsDesc' | 'settingsDesc'> = {
  students: 'studentDesc', classrooms: 'classroomsDesc', attendance: 'attendanceDesc', academics: 'academicsDesc', finance: 'financeDesc', reports: 'reportsDesc', settings: 'settingsDesc',
};

function App() {
  const [lang, setLang] = useState<Lang>('en');
  const authEnabled = import.meta.env.VITE_AUTH_ENABLED === 'true';
  const [authenticated, setAuthenticated] = useState(() => !authEnabled || Boolean(window.sessionStorage.getItem('school_access_token')));
  const [currentUser, setCurrentUser] = useState<{ user_id: string; email: string; role: string; organization_id: string } | null>(null);
  useEffect(() => {
    const expire = () => { setAuthenticated(false); setCurrentUser(null); };
    window.addEventListener('school-auth-expired', expire);
    return () => window.removeEventListener('school-auth-expired', expire);
  }, []);
  useEffect(() => {
    if (!authEnabled || !authenticated) return;
    let cancelled = false;
    const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
    apiFetch(`${apiBase}/api/v1/auth/me`).then(async response => {
      if (!response.ok) throw new Error(`Authentication profile request failed: ${response.status}`);
      return response.json() as Promise<{ user_id: string; email: string; role: string; organization_id: string }>;
    }).then(user => { if (!cancelled) setCurrentUser(user); }).catch(() => {
      if (!cancelled) { clearAccessToken(); setAuthenticated(false); setCurrentUser(null); }
    });
    return () => { cancelled = true; };
  }, [authEnabled, authenticated]);
  const [page, setPage] = useState<Page>('dashboard');
  const [mobileNav, setMobileNav] = useState(false);
  const [query, setQuery] = useState('');
  const t = copy[lang];
  const isAm = lang === 'am';
  const activities = useMemo(() => t.activity.map((title, i) => ({ title, ago: t.ago[i], i })), [t]);
  if (authEnabled && !authenticated) return <LoginPage isAm={isAm} onLogin={() => setAuthenticated(true)} />;

  const pageName = (id: Page) => id === 'dashboard' ? t.dashboard : id === 'students' ? t.students : id === 'classrooms' ? t.classrooms : id === 'attendance' ? t.attendance : id === 'academics' ? t.academics : id === 'finance' ? t.finance : id === 'reports' ? t.reports : t.settings;

  return (
    <div className={isAm ? 'app amharic' : 'app'}>
      {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand">
          <div className="brand-mark"><GraduationCap size={25} strokeWidth={2.2} /></div>
          <div><strong>{t.school}</strong><span>{t.branch}</span></div>
        </div>
        <div className="nav-caption">{t.overview}</div>
        <nav>
          {nav.map(({ id, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => { setPage(id); setMobileNav(false); }}><Icon size={18} /><span>{pageName(id)}</span>{id === 'finance' && <i className="nav-dot" />}</button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="sync-card"><div className="sync-icon"><CloudOff size={18} /></div><div><strong>{t.offlineReady}</strong><span>{t.lastSync}</span></div><span className="sync-light" /></div>
          <div className="sidebar-profile"><div className="avatar">{(currentUser?.email || 'SA').slice(0, 2).toUpperCase()}</div><div className="profile-copy"><strong>{authEnabled ? (currentUser?.role || (isAm ? 'ተጠቃሚ' : 'User')) : t.admin}</strong><span>{authEnabled ? (currentUser?.email || '') : 'admin@aster.school'}</span></div><ChevronDown size={16} className="profile-chevron" /></div>{authEnabled && <button className="logout-button" onClick={() => { clearAccessToken(); setAuthenticated(false); }}>{isAm ? 'ውጣ' : 'Sign out'}</button>}
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu icon-button" aria-label="Open menu" onClick={() => setMobileNav(true)}><Menu size={20} /></button>
          <div className="breadcrumbs">{t.school}<span>/</span><strong>{pageName(page)}</strong></div>
          <div className="topbar-actions">
            <label className="search-box"><Search size={17} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t.search} /></label>
            <button className="language-button" onClick={() => setLang(isAm ? 'en' : 'am')}><Languages size={17} /><span>{isAm ? 'አማ' : 'EN'}</span></button>
            <button className="icon-button notification-button" aria-label={t.notifications}><Activity size={19} /><i /></button>
            <div className="top-avatar" aria-label={currentUser?.email || t.admin}>{authEnabled ? (currentUser?.email || 'U').slice(0, 2).toUpperCase() : 'SA'}</div>
          </div>
        </header>

        <div className="page-content">
          {page === 'dashboard' ? <>
            <div className="welcome-row"><div><div className="eyebrow">{t.overview}</div><h1>{t.welcome}</h1><p>{t.subtitle}</p></div><div className="date-pill"><CalendarCheck size={16} /><span>Monday, October 19, 2026</span><ChevronDown size={15} /></div></div>
            <div className="demo-banner"><span className="demo-dot" /><span>{t.demoNotice}</span><span className="demo-tag">{t.demo}</span></div>
            <section className="stats-grid">
              <StatCard title={t.totalStudents} value="1,284" change="8.2%" positive note={t.fromLastMonth} icon={<Users size={19} />} iconClass="mint" spark={[24, 32, 29, 42, 37, 48, 53, 61]} />
              <StatCard title={t.presentToday} value="1,196" change="93.1%" positive note={t.attendanceRate} icon={<CalendarCheck size={19} />} iconClass="blue" spark={[45, 42, 51, 47, 58, 56, 63, 61]} />
              <StatCard title={t.feeCollection} value="ETB 284,500" change="12.4%" positive note={t.collectedThisMonth} icon={<CircleDollarSign size={19} />} iconClass="gold" spark={[22, 28, 25, 37, 33, 45, 43, 58]} />
              <StatCard title={t.pendingFees} value="ETB 96,250" change="4.6%" positive={false} note={t.outstandingBalance} icon={<ClipboardList size={19} />} iconClass="rose" spark={[62, 55, 58, 49, 52, 44, 41, 38]} />
            </section>

            <section className="content-grid">
              <div className="panel attendance-panel">
                <div className="panel-heading"><div><h2>{t.weeklyAttendance}</h2><p>Oct 12 – Oct 18, 2026</p></div><button className="subtle-button">This week <ChevronDown size={14} /></button></div>
                <div className="chart-legend"><span><i className="legend-present" />Present</span><span><i className="legend-absent" />Absent</span></div>
                <div className="bar-chart" role="img" aria-label="Illustrative weekly attendance chart">
                  {[['91','9'],['95','5'],['88','12'],['93','7'],['96','4'],['73','27'],['61','39']].map(([present, absent], i) => <div className="bar-group" key={i}><div className="bar-stack"><div className="bar-present" style={{height: `${present}%`}} /><div className="bar-absent" style={{height: `${absent}%`}} /></div><span>{t.days[i]}</span></div>)}
                </div>
                <div className="chart-footer"><div><span className="chart-footer-dot" /><div><strong>91.4%</strong><small>Average attendance</small></div></div><span className="chart-note"><ArrowUpRight size={15} /> 2.8% vs last week</span></div>
              </div>

              <div className="panel activity-panel">
                <div className="panel-heading"><div><h2>{t.recentActivity}</h2><p>Latest school updates</p></div><button className="text-button">{t.viewAll}</button></div>
                <div className="activity-list">{activities.map(({ title, ago, i }) => <div className="activity-item" key={title}><div className={`activity-icon activity-${i}`}>{i === 0 ? <Users size={17} /> : i === 1 ? <CalendarCheck size={17} /> : i === 2 ? <CircleDollarSign size={17} /> : <BookOpen size={17} />}</div><div className="activity-copy"><strong>{title}</strong><span>{ago}</span></div><CheckCircle2 className="activity-check" size={16} /></div>)}</div>
                <button className="activity-footer">View activity log <ArrowUpRight size={15} /></button>
              </div>
            </section>

            <section className="bottom-grid">
              <div className="panel quick-panel"><div className="panel-heading"><div><h2>{t.quickActions}</h2><p>Common tasks for today</p></div></div><div className="quick-actions"><QuickAction icon={<Users size={19} />} title={t.addStudent} color="mint" onClick={() => setPage('students')} /><QuickAction icon={<CalendarCheck size={19} />} title={t.recordAttendance} color="blue" onClick={() => setPage('attendance')} /><QuickAction icon={<BookOpen size={19} />} title={t.enterMarks} color="gold" onClick={() => setPage('academics')} /><QuickAction icon={<CircleDollarSign size={19} />} title={t.recordPayment} color="rose" onClick={() => setPage('finance')} /></div></div>
              <SyncPanel isAm={isAm} organizationId={currentUser?.organization_id || import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization'} actorId={currentUser?.user_id || 'development-user'} />
            </section>
          </> : page === 'students' ? <StudentDirectory t={t} query={query} /> : page === 'classrooms' ? <ClassroomsPage t={t} isAm={isAm} /> : page === 'attendance' ? <AttendancePage t={t} isAm={isAm} actorId={currentUser?.user_id || 'development-user'} /> : page === 'academics' ? <AcademicsPage t={t} isAm={isAm} actorId={currentUser?.user_id || 'development-user'} /> : page === 'finance' ? <FinancePage isAm={isAm} /> : page === 'reports' ? <ReportsPage t={t} isAm={isAm} /> : <ModulePage page={page} t={t} pageName={pageName(page)} onDashboard={() => setPage('dashboard')} titleKey={page === 'dashboard' ? undefined : pageTitleKey[page]} descKey={page === 'dashboard' ? undefined : pageDescKey[page]} />}
          <footer className="app-footer"><span>School Management System <span className="footer-version">v0.1.0 · Starter</span></span><span><span className="footer-status" /> {t.demo} · No live database connected</span></footer>
        </div>
      </main>
    </div>
  );
}

type GuardianRecord = { guardian_id: string; student_id: string; given_name: string; family_name: string; relationship: string; phone: string | null; email: string | null; is_primary: boolean; portal_access: boolean; };

type StudentAuditEvent = { event_id: string; event_type: string; entity_type: string; entity_id: string; created_at: string; details: Record<string, unknown> };
type StudentRecord = {
  student_id: string; organization_id: string; branch_id: string; given_name: string;
  middle_name: string | null; family_name: string; date_of_birth: string | null;
  sex_at_registration: 'female' | 'male' | 'unspecified'; external_reference: string | null;
  status: string; created_at: string;
};

function StudentDirectory({ t, query }: { t: typeof copy.en; query: string }) {
  const [students, setStudents] = useState<StudentRecord[]>([]);
  const [studentTotal, setStudentTotal] = useState(0);
  const [studentOffset, setStudentOffset] = useState(0);
  const studentRequestId = useRef(0);
  const previousStudentQuery = useRef(query);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [guardianStudent, setGuardianStudent] = useState<StudentRecord | null>(null);
  const [historyStudent, setHistoryStudent] = useState<StudentRecord | null>(null);
  const [historyEvents, setHistoryEvents] = useState<StudentAuditEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [deactivateStudent, setDeactivateStudent] = useState<StudentRecord | null>(null);
  const [deactivateReason, setDeactivateReason] = useState('');
  const [deactivating, setDeactivating] = useState(false);
  const isAm = t.studentsTitle === copy.am.studentsTitle;
  const [guardians, setGuardians] = useState<GuardianRecord[]>([]);
  const [guardianLoading, setGuardianLoading] = useState(false);
  const [guardianSaving, setGuardianSaving] = useState(false);
  const [guardianError, setGuardianError] = useState('');
  const [guardianForm, setGuardianForm] = useState({ given_name: '', family_name: '', relationship: 'parent', phone: '', email: '', is_primary: false });
  const [form, setForm] = useState({ given_name: '', middle_name: '', family_name: '', branch_id: 'main', date_of_birth: '', sex_at_registration: 'unspecified', external_reference: '' });
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';

  async function loadStudents(search = query, offset = studentOffset) {
    const requestId = ++studentRequestId.current;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: '50', offset: String(offset) });
      if (search.trim()) params.set('q', search.trim());
      const response = await apiFetch(`${apiBase}/api/v1/students?${params.toString()}`, { headers: { 'X-Organization-ID': orgId } });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const data = await response.json() as { items: StudentRecord[]; total: number; limit: number; offset: number };
      // Ignore late responses from an older search/page so stale data cannot overwrite the latest view.
      if (requestId !== studentRequestId.current) return;
      setStudents(data.items); setStudentTotal(data.total);
    } catch {
      if (requestId === studentRequestId.current) setError(t.apiError);
    } finally {
      if (requestId === studentRequestId.current) setLoading(false);
    }
  }
  useEffect(() => {
    if (previousStudentQuery.current !== query) {
      previousStudentQuery.current = query;
      if (studentOffset !== 0) {
        setStudentOffset(0);
        return;
      }
    }
    void loadStudents(query, studentOffset);
  }, [apiBase, orgId, query, studentOffset]);

  async function submitStudent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(''); setNotice('');
    const payload = { ...form, middle_name: form.middle_name.trim() || null, date_of_birth: form.date_of_birth || null, external_reference: form.external_reference.trim() || null };
    try {
      const response = await apiFetch(`${apiBase}/api/v1/students`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId }, body: JSON.stringify(payload) });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(body?.detail || `API returned ${response.status}`);
      }
      setForm({ given_name: '', middle_name: '', family_name: '', branch_id: 'main', date_of_birth: '', sex_at_registration: 'unspecified', external_reference: '' });
      setFormOpen(false); setNotice(t.saved); await loadStudents();
    } catch (e) { setError(e instanceof Error && e.message !== t.apiError ? e.message : t.apiError); }
    finally { setSaving(false); }
  }
  async function openHistory(student: StudentRecord) {
    setHistoryStudent(student); setHistoryLoading(true); setHistoryError(''); setHistoryEvents([]);
    try {
      const response = await apiFetch(`${apiBase}/api/v1/students/${encodeURIComponent(student.student_id)}/history?limit=100`, { headers: { 'X-Organization-ID': orgId } });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const data = await response.json() as { items: StudentAuditEvent[] };
      setHistoryEvents(data.items);
    } catch (e) { setHistoryError(e instanceof Error ? e.message : t.apiError); }
    finally { setHistoryLoading(false); }
  }
  async function submitDeactivation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!deactivateStudent) return;
    const reason = deactivateReason.trim();
    if (reason.length < 3) { setError(isAm ? 'ምክንያቱ ቢያንስ 3 ቁምፊ መሆን አለበት።' : 'Reason must contain at least 3 non-whitespace characters.'); return; }
    setDeactivating(true); setError(''); setNotice('');
    try {
      const response = await apiFetch(`${apiBase}/api/v1/students/${encodeURIComponent(deactivateStudent.student_id)}/deactivate`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId }, body: JSON.stringify({ reason }) });
      if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
      setDeactivateStudent(null); setDeactivateReason(''); setNotice(isAm ? 'የተማሪው ሁኔታ ተቀይሯል።' : 'Student deactivated; the reason was added to the audit history.');
      await loadStudents();
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setDeactivating(false); }
  }
  async function openGuardians(student: StudentRecord) {
    setGuardianStudent(student); setGuardianLoading(true); setGuardianError(''); setGuardians([]);
    try {
      const response = await apiFetch(`${apiBase}/api/v1/students/${encodeURIComponent(student.student_id)}/guardians`, { headers: { 'X-Organization-ID': orgId } });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setGuardians(await response.json() as GuardianRecord[]);
    } catch { setGuardianError(t.apiError); }
    finally { setGuardianLoading(false); }
  }
  async function submitGuardian(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!guardianStudent) return;
    setGuardianSaving(true); setGuardianError('');
    try {
      const response = await apiFetch(`${apiBase}/api/v1/students/${encodeURIComponent(guardianStudent.student_id)}/guardians`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId },
        body: JSON.stringify({ ...guardianForm, phone: guardianForm.phone.trim() || null, email: guardianForm.email.trim() || null }),
      });
      if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
      const created = await response.json() as GuardianRecord;
      setGuardians(old => [...old, created]);
      setGuardianForm({ given_name: '', family_name: '', relationship: 'parent', phone: '', email: '', is_primary: false });
    } catch (e) { setGuardianError(e instanceof Error ? e.message : t.apiError); }
    finally { setGuardianSaving(false); }
  }
  const update = (key: keyof typeof form, value: string) => setForm(old => ({ ...old, [key]: value }));
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">API-connected development module</div><h1>{t.studentsTitle}</h1><p>{t.studentDesc}</p></div><div className="directory-actions"><button className="secondary-button" onClick={() => void loadStudents()} disabled={loading}><RefreshCw size={15} /> {t.reload}</button><button className="primary-button" onClick={() => { setFormOpen(v => !v); setNotice(''); }}><Plus size={16} /> {t.createStudent}</button></div></div>
    <div className="prototype-alert"><ShieldCheck size={17} /><span>{t.prototypeWarning}</span></div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status">{notice}</div>}
    {formOpen && <form className="student-form" onSubmit={submitStudent}><h2>{t.createStudent}</h2><div className="student-form-grid">
      <label>{t.firstName}<input required maxLength={120} value={form.given_name} onChange={e => update('given_name', e.target.value)} /></label>
      <label>{t.middleName}<input maxLength={120} value={form.middle_name} onChange={e => update('middle_name', e.target.value)} /></label>
      <label>{t.familyName}<input required maxLength={120} value={form.family_name} onChange={e => update('family_name', e.target.value)} /></label>
      <label>{t.branchId}<input required maxLength={64} value={form.branch_id} onChange={e => update('branch_id', e.target.value)} /></label>
      <label>{t.birthDate}<input type="date" value={form.date_of_birth} onChange={e => update('date_of_birth', e.target.value)} /></label>
      <label>{t.sex}<select value={form.sex_at_registration} onChange={e => update('sex_at_registration', e.target.value)}><option value="unspecified">{t.unspecified}</option><option value="female">{t.female}</option><option value="male">{t.male}</option></select></label>
      <label className="full-field">{t.externalRef}<input maxLength={80} value={form.external_reference} onChange={e => update('external_reference', e.target.value)} /></label>
    </div><div className="form-actions"><button type="button" className="secondary-button" onClick={() => setFormOpen(false)}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Saving…' : t.createStudent}</button></div></form>}
    <div className="directory-toolbar"><div><strong>{studentTotal}</strong> {t.totalRecords}</div><span>Organization: {orgId}</span></div>
    <div className="student-table-wrap"><table className="student-table"><thead><tr><th>{t.firstName}</th><th>{t.familyName}</th><th>{t.branchId}</th><th>{t.birthDate}</th><th>{t.sex}</th><th>Status</th><th>Family</th><th>{isAm ? 'ታሪክ / ሁኔታ' : 'History / status'}</th></tr></thead><tbody>
      {loading ? <tr><td colSpan={8} className="table-message">{t.loading}</td></tr> : error && students.length === 0 ? <tr><td colSpan={8} className="table-message">—</td></tr> : students.length === 0 ? <tr><td colSpan={8} className="table-message">{t.noStudents}</td></tr> : students.map(student => <tr key={student.student_id}><td><strong>{student.given_name}</strong>{student.middle_name ? ` ${student.middle_name}` : ''}</td><td>{student.family_name}</td><td>{student.branch_id}</td><td>{student.date_of_birth || '—'}</td><td>{student.sex_at_registration}</td><td><span className="student-status">{student.status}</span></td><td><button className="secondary-button compact-button" onClick={() => void openGuardians(student)}>{isAm ? 'ወላጆች' : 'Guardians'}</button></td><td><div className="directory-actions"><button className="secondary-button compact-button" onClick={() => void openHistory(student)}>{isAm ? 'ታሪክ' : 'History'}</button>{student.status === 'active' && <button className="secondary-button compact-button" onClick={() => { setDeactivateStudent(student); setDeactivateReason(''); setError(''); }}>{isAm ? 'አቦዝን' : 'Deactivate'}</button>}</div></td></tr>)}
    </tbody></table></div>
    <div className="directory-toolbar"><span>{studentTotal === 0 ? '0' : `${studentOffset + 1}–${Math.min(studentOffset + students.length, studentTotal)}`} / {studentTotal}</span><div className="directory-actions"><button className="secondary-button" disabled={loading || studentOffset === 0} onClick={() => setStudentOffset(value => Math.max(0, value - 50))}>{isAm ? 'ቀዳሚ' : 'Previous'}</button><button className="secondary-button" disabled={loading || studentOffset + students.length >= studentTotal} onClick={() => setStudentOffset(value => value + 50)}>{isAm ? 'ቀጣይ' : 'Next'}</button></div></div>
    {deactivateStudent && <form className="student-form" onSubmit={submitDeactivation}>
      <h2>{isAm ? 'ተማሪን ከንቁ ሁኔታ ማስወጣት' : 'Deactivate student'} — {deactivateStudent.given_name} {deactivateStudent.family_name}</h2>
      <p>{isAm ? 'መዝገቡ አይሰረዝም፤ ምክንያቱ በኦዲት ታሪክ ይቀመጣል።' : 'The record will not be deleted. The reason is retained in the audit history.'}</p>
      <label>{isAm ? 'ምክንያት (ያስፈልጋል)' : 'Reason (required)'}<textarea required minLength={3} maxLength={500} value={deactivateReason} onChange={e => setDeactivateReason(e.target.value)} /></label>
      <div className="form-actions"><button type="button" className="secondary-button" onClick={() => setDeactivateStudent(null)}>{isAm ? 'ይቅር' : 'Cancel'}</button><button type="submit" className="primary-button" disabled={deactivating || deactivateReason.trim().length < 3}>{deactivating ? (isAm ? 'በማስቀመጥ ላይ…' : 'Saving…') : (isAm ? 'ሁኔታ ቀይር' : 'Confirm deactivation')}</button></div>
    </form>}
    {historyStudent && <div className="guardian-panel">
      <div className="directory-heading"><div><div className="eyebrow">{isAm ? 'የኦዲት መዝገብ' : 'Audit trail'}</div><h2>{isAm ? 'የተማሪ ታሪክ' : 'Student history'} — {historyStudent.given_name} {historyStudent.family_name}</h2></div><button className="secondary-button" onClick={() => setHistoryStudent(null)}>{isAm ? 'ዝጋ' : 'Close'}</button></div>
      {historyError && <div className="api-error" role="alert">{historyError}</div>}
      {historyLoading ? <p>{isAm ? 'ታሪክ እየተጫነ ነው…' : 'Loading history…'}</p> : historyEvents.length === 0 ? <p>{isAm ? 'የታሪክ መዝገብ አልተገኘም።' : 'No audit events found.'}</p> : <div className="guardian-list">{historyEvents.map(item => <div className="guardian-row" key={item.event_id}><div><strong>{item.event_type}</strong><span>{item.created_at}</span></div><div><span>{JSON.stringify(item.details)}</span></div></div>)}</div>}
    </div>}
    {guardianStudent && <div className="guardian-panel">
      <div className="directory-heading"><div><div className="eyebrow">Student family links</div><h2>Guardians — {guardianStudent.given_name} {guardianStudent.family_name}</h2><p>Guardian portal access is not granted by this form.</p></div><button className="secondary-button" onClick={() => setGuardianStudent(null)}>Close</button></div>
      {guardianError && <div className="api-error" role="alert">{guardianError}</div>}
      {guardianLoading ? <p>Loading guardians…</p> : guardians.length === 0 ? <p>No guardians linked yet.</p> : <div className="guardian-list">{guardians.map(g => <div className="guardian-row" key={g.guardian_id}><div><strong>{g.given_name} {g.family_name}</strong><span>{g.relationship}{g.is_primary ? ' · Primary contact' : ''}</span></div><div>{g.phone || '—'}<span>{g.email || '—'}</span></div><span className="student-status">Portal access off</span></div>)}</div>}
      <form className="student-form" onSubmit={submitGuardian}><h3>Add guardian</h3><div className="student-form-grid">
        <label>Given name<input required maxLength={120} value={guardianForm.given_name} onChange={e => setGuardianForm(v => ({...v, given_name: e.target.value}))} /></label>
        <label>Family name<input required maxLength={120} value={guardianForm.family_name} onChange={e => setGuardianForm(v => ({...v, family_name: e.target.value}))} /></label>
        <label>Relationship<select value={guardianForm.relationship} onChange={e => setGuardianForm(v => ({...v, relationship: e.target.value}))}><option value="parent">Parent</option><option value="guardian">Guardian</option><option value="grandparent">Grandparent</option><option value="other">Other</option></select></label>
        <label>Phone<input maxLength={160} value={guardianForm.phone} onChange={e => setGuardianForm(v => ({...v, phone: e.target.value}))} /></label>
        <label>Email<input type="email" maxLength={160} value={guardianForm.email} onChange={e => setGuardianForm(v => ({...v, email: e.target.value}))} /></label>
        <label className="checkbox-field"><input type="checkbox" checked={guardianForm.is_primary} onChange={e => setGuardianForm(v => ({...v, is_primary: e.target.checked}))} /> Primary contact</label>
      </div><div className="form-actions"><button type="submit" className="primary-button" disabled={guardianSaving}>{guardianSaving ? 'Saving…' : 'Add guardian'}</button></div></form>
    </div>}
  </section>;
}

type AttendanceRecord = {
  attendance_id: string; organization_id: string; branch_id: string; student_id: string;
  attendance_date: string; status: 'present' | 'absent' | 'late' | 'excused'; note: string | null;
  created_at: string; updated_at: string;
};
type AttendanceSummary = { total_recorded: number; present: number; absent: number; late: number; excused: number; attendance_rate_pct: number | null };
type AttendanceSection = { section_id: string; name: string; branch_id: string; academic_year: string; class_level: string; status?: string };
type AttendanceStudent = { student_id: string; given_name: string; middle_name: string | null; family_name: string; branch_id: string };

function AttendancePage({ t, isAm, actorId }: { t: typeof copy.en; isAm: boolean; actorId: string }) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const today = new Date();
  const todayText = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const [students, setStudents] = useState<AttendanceStudent[]>([]);
  const [sections, setSections] = useState<AttendanceSection[]>([]);
  const [selectedSectionId, setSelectedSectionId] = useState('');
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [date, setDate] = useState(todayText);
  const [reportStart, setReportStart] = useState(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`);
  const [reportEnd, setReportEnd] = useState(todayText);
  const [summary, setSummary] = useState<AttendanceSummary | null>(null);
  const [studentId, setStudentId] = useState('');
  const [status, setStatus] = useState<AttendanceRecord['status']>('present');
  const [bulkStatuses, setBulkStatuses] = useState<Record<string, AttendanceRecord['status']>>({});
  const [bulkSaving, setBulkSaving] = useState(false);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [correctionId, setCorrectionId] = useState('');
  const [correctionStatus, setCorrectionStatus] = useState<AttendanceRecord['status']>('present');
  const [correctionReason, setCorrectionReason] = useState('');

  const labels = isAm ? {
    title: 'የተማሪ መገኘት', desc: 'የቀን መገኘትን ይመዝግቡ፣ ያጣሩ እና ማስተካከያዎችን ይመልከቱ።',
    record: 'መገኘት ይመዝግቡ', bulkTitle: 'የክፍል መገኘት በአንድ ጊዜ', bulkSubmit: 'ያልተመዘገቡትን ተማሪዎች መዝግብ', bulkEmpty: 'ለዚህ ቀን ያልተመዘገበ ተማሪ የለም።', bulkSaved: 'የክፍል መገኘት ተመዝግቧል።', sectionScope: 'ሴክሽን ይምረጡ (አማራጭ)', allStudents: 'ሁሉም ተማሪዎች', chooseSection: 'ሴክሽን ይምረጡ', date: 'ቀን', student: 'ተማሪ', status: 'ሁኔታ', note: 'ማስታወሻ (አማራጭ)',
    submit: 'መዝግብ', saving: 'በማስቀመጥ ላይ…', refresh: 'እንደገና ጫን', records: 'የመገኘት መዝገቦች', empty: 'ለዚህ ቀን መዝገብ የለም።',
    choose: 'ተማሪ ይምረጡ', present: 'ተገኝቷል', absent: 'አልተገኘም', late: 'ዘግይቷል', excused: 'በፈቃድ ቀርቷል',
    correction: 'መዝገብ ማስተካከያ', reason: 'የማስተካከያ ምክንያት (ያስፈልጋል)', saveCorrection: 'ማስተካከያ አስቀምጥ', cancel: 'ሰርዝ', prototype: t.prototypeWarning, report: 'የመገኘት ማጠቃለያ', startDate: 'ከቀን', endDate: 'እስከ ቀን', total: 'ጠቅላላ መዝገቦች', rate: 'የመገኘት መጠን',
    loadError: t.apiError, saved: 'የመገኘት መዝገብ ተቀምጧል።', corrected: 'ማስተካከያው ተቀምጧል።', duplicate: 'ለዚህ ተማሪ በዚህ ቀን መዝገብ አስቀድሞ አለ።',
  } : {
    title: 'Attendance register', desc: 'Record daily attendance, filter by date, and correct entries with an audit reason.',
    record: 'Record attendance', bulkTitle: 'Bulk class attendance', bulkSubmit: 'Save unrecorded students', bulkEmpty: 'All students already have a record for this date.', bulkSaved: 'Bulk attendance saved.', sectionScope: 'Limit to section (optional)', allStudents: 'All students (not section restricted)', chooseSection: 'Choose a section', date: 'Date', student: 'Student', status: 'Status', note: 'Note (optional)',
    submit: 'Save attendance', saving: 'Saving…', refresh: 'Refresh', records: 'Attendance records', empty: 'No records found for this date.',
    choose: 'Choose a student', present: 'Present', absent: 'Absent', late: 'Late', excused: 'Excused',
    correction: 'Correct attendance record', reason: 'Correction reason (required)', saveCorrection: 'Save correction', cancel: 'Cancel', prototype: t.prototypeWarning, report: 'Attendance summary', startDate: 'From date', endDate: 'To date', total: 'Total recorded', rate: 'Attendance rate',
    loadError: t.apiError, saved: 'Attendance record saved.', corrected: 'Correction saved.', duplicate: 'An attendance record already exists for this student on this date.',
  };
  const statusLabels: Record<AttendanceRecord['status'], string> = { present: labels.present, absent: labels.absent, late: labels.late, excused: labels.excused };

  async function load() {
    setLoading(true); setError('');
    try {
      const [studentResponse, attendanceResponse, sectionResponse] = await Promise.all([
        apiFetch(`${apiBase}/api/v1/students?limit=500`, { headers: { 'X-Organization-ID': orgId } }),
        apiFetch(`${apiBase}/api/v1/attendance?attendance_date=${encodeURIComponent(date)}&limit=500`, { headers: { 'X-Organization-ID': orgId } }),
        apiFetch(`${apiBase}/api/v1/classrooms/sections`, { headers: { 'X-Organization-ID': orgId } }),
      ]);
      if (!studentResponse.ok || !attendanceResponse.ok || !sectionResponse.ok) throw new Error('API request failed');
      const studentData = await studentResponse.json() as { items: StudentRecord[] };
      const attendanceData = await attendanceResponse.json() as { items: AttendanceRecord[] };
      const sectionData = await sectionResponse.json() as { items: AttendanceSection[] };
      let visibleStudents: AttendanceStudent[] = studentData.items;
      if (selectedSectionId) {
        const rosterResponse = await apiFetch(`${apiBase}/api/v1/classrooms/sections/${encodeURIComponent(selectedSectionId)}/students`, { headers: { 'X-Organization-ID': orgId } });
        if (!rosterResponse.ok) throw new Error('Could not load the selected section roster');
        const rosterData = await rosterResponse.json() as { items: AttendanceStudent[] };
        visibleStudents = rosterData.items;
      }
      setSections(sectionData.items); setStudents(visibleStudents); setRecords(attendanceData.items);
      setBulkStatuses(previous => { const next = { ...previous }; for (const student of visibleStudents) if (!next[student.student_id]) next[student.student_id] = 'present'; return next; });
    } catch { setError(labels.loadError); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [apiBase, orgId, date, selectedSectionId]);
  useEffect(() => {
    if (reportStart > reportEnd) { setSummary(null); return; }
    let cancelled = false;
    apiFetch(`${apiBase}/api/v1/attendance/summary?start_date=${encodeURIComponent(reportStart)}&end_date=${encodeURIComponent(reportEnd)}`, { headers: { 'X-Organization-ID': orgId } })
      .then(response => { if (!response.ok) throw new Error('Summary request failed'); return response.json() as Promise<AttendanceSummary>; })
      .then(data => { if (!cancelled) setSummary(data); })
      .catch(() => { if (!cancelled) setSummary(null); });
    return () => { cancelled = true; };
  }, [apiBase, orgId, reportStart, reportEnd]);

  async function queueAttendanceMutation(payload: { student_id: string; attendance_date: string; status: AttendanceRecord['status']; note: string | null }) {
    const cryptoApi = globalThis.crypto;
    if (!cryptoApi?.randomUUID) throw new Error(isAm ? 'የደህንነት መለያ ማመንጨት አልተቻለም። ወደ ኦንላይን ይመለሱ።' : 'Secure mutation IDs are unavailable; reconnect and try again.');
    let deviceId = 'temporary-device-session';
    try {
      const saved = window.localStorage.getItem('school_device_id');
      if (saved) deviceId = saved;
      else { deviceId = cryptoApi.randomUUID(); window.localStorage.setItem('school_device_id', deviceId); }
    } catch { /* Keep this session-scoped fallback if local storage is blocked. */ }
    const envelope = createMutationEnvelope({
      mutationId: cryptoApi.randomUUID(), organizationId: orgId, deviceId, actorId,
      entityType: 'attendance_record', entityId: cryptoApi.randomUUID(), operation: 'create',
      baseVersion: null, payload,
    });
    await enqueueMutation(envelope);
    return envelope;
  }

  function addQueuedAttendanceToView(payload: { student_id: string; attendance_date: string; status: AttendanceRecord['status']; note: string | null }, mutationId: string) {
    const student = students.find(item => item.student_id === payload.student_id);
    const now = new Date().toISOString();
    setRecords(previous => previous.some(record => record.attendance_id === mutationId || (record.student_id === payload.student_id && record.attendance_date === payload.attendance_date))
      ? previous
      : [...previous, {
        attendance_id: mutationId, organization_id: orgId, branch_id: student?.branch_id || '',
        student_id: payload.student_id, attendance_date: payload.attendance_date, status: payload.status,
        note: payload.note, created_at: now, updated_at: now,
      }].sort((a, b) => a.attendance_date.localeCompare(b.attendance_date)));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(''); setNotice('');
    try {
      const payload = { student_id: studentId, attendance_date: date, status, note: note.trim() || null };
      if (!navigator.onLine) {
        const queued = await queueAttendanceMutation(payload);
        addQueuedAttendanceToView(payload, queued.entity_id);
        setNotice(isAm ? 'ከመስመር ውጭ ተቀምጧል፤ ኢንተርኔት ሲመለስ ከSync ገጽ ይላኩ።' : 'Saved offline. Open the Sync panel when connectivity returns to send it.');
        setNote('');
        return;
      }
      let response: Response;
      try {
        response = await apiFetch(`${apiBase}/api/v1/attendance`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId }, body: JSON.stringify(payload) });
      } catch (networkError) {
        if (!(networkError instanceof TypeError)) throw networkError;
        const queued = await queueAttendanceMutation(payload);
        addQueuedAttendanceToView(payload, queued.entity_id);
        setNotice(isAm ? 'ግንኙነት ስለተቋረጠ በአካባቢው ተቀምጧል፤ ከSync ገጽ ይላኩ።' : 'Connection failed; attendance was saved locally. Use the Sync panel to retry.');
        setNote('');
        return;
      }
      if (!response.ok) {
        if (response.status === 409) throw new Error(labels.duplicate);
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(body?.detail || `API returned ${response.status}`);
      }
      setNotice(labels.saved); setNote(''); await load();
    } catch (e) { setError(e instanceof Error ? e.message : labels.loadError); }
    finally { setSaving(false); }
  }
  async function submitBulk() {
    const existing = new Set(records.map(record => record.student_id));
    const pending = students.filter(student => !existing.has(student.student_id));
    if (!pending.length) { setNotice(labels.bulkEmpty); return; }
    setBulkSaving(true); setError(''); setNotice('');
    try {
      const queueBulkAttendance = async () => {
        // Queue each student as an independently idempotent create. The server's
        // sync protocol currently accepts attendance_record mutations, not bulk commands.
        for (const student of pending) {
          const payload = {
            student_id: student.student_id,
            attendance_date: date,
            status: bulkStatuses[student.student_id] || 'present',
            note: null,
          } as const;
          const queued = await queueAttendanceMutation(payload);
          addQueuedAttendanceToView(payload, queued.entity_id);
        }
      };
      if (!navigator.onLine) {
        await queueBulkAttendance();
        setNotice(isAm
          ? `ከመስመር ውጭ ${pending.length} የመገኘት መዝገቦች ተቀምጠዋል፤ ከSync ገጽ ይላኩ።`
          : `${pending.length} attendance records saved offline. Use the Sync panel to send them later.`);
        return;
      }
      const bulkPath = selectedSectionId
        ? `/api/v1/attendance/sections/${encodeURIComponent(selectedSectionId)}/bulk`
        : '/api/v1/attendance/bulk';
      let response: Response;
      try {
        response = await apiFetch(`${apiBase}${bulkPath}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId },
          body: JSON.stringify({ attendance_date: date, records: pending.map(student => ({ student_id: student.student_id, status: bulkStatuses[student.student_id] || 'present' })) }),
        });
      } catch (networkError) {
        if (!(networkError instanceof TypeError)) throw networkError;
        await queueBulkAttendance();
        setNotice(isAm
          ? `ግንኙነት ተቋርጧል፤ ${pending.length} መዝገቦች በአካባቢው ተቀምጠዋል።`
          : `Connection failed; ${pending.length} attendance records were queued locally for later sync.`);
        return;
      }
      if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
      setNotice(labels.bulkSaved); await load();
    } catch (e) { setError(e instanceof Error ? e.message : labels.loadError); }
    finally { setBulkSaving(false); }
  }

  async function saveCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!correctionId) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const response = await apiFetch(`${apiBase}/api/v1/attendance/${encodeURIComponent(correctionId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-Organization-ID': orgId }, body: JSON.stringify({ status: correctionStatus, reason: correctionReason.trim() }) });
      if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
      setCorrectionId(''); setCorrectionReason(''); setNotice(labels.corrected); await load();
    } catch (e) { setError(e instanceof Error ? e.message : labels.loadError); }
    finally { setSaving(false); }
  }
  const studentName = (id: string) => { const s = students.find(item => item.student_id === id); return s ? `${s.given_name} ${s.middle_name ? `${s.middle_name} ` : ''}${s.family_name}` : id; };
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">API-connected development module</div><h1>{labels.title}</h1><p>{labels.desc}</p></div><div className="directory-actions"><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} /> {labels.refresh}</button></div></div>
    <div className="prototype-alert"><ShieldCheck size={17} /><span>{labels.prototype}</span></div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status">{notice}</div>}
    <div className="student-form attendance-report"><h2>{labels.report}</h2><div className="student-form-grid"><label>{labels.startDate}<input type="date" value={reportStart} max={reportEnd} onChange={e => setReportStart(e.target.value)} /></label><label>{labels.endDate}<input type="date" value={reportEnd} min={reportStart} onChange={e => setReportEnd(e.target.value)} /></label></div>
      <div className="attendance-summary-grid"><div><span>{labels.total}</span><strong>{summary?.total_recorded ?? '—'}</strong></div><div><span>{labels.present}</span><strong>{summary?.present ?? '—'}</strong></div><div><span>{labels.absent}</span><strong>{summary?.absent ?? '—'}</strong></div><div><span>{labels.late}</span><strong>{summary?.late ?? '—'}</strong></div><div><span>{labels.excused}</span><strong>{summary?.excused ?? '—'}</strong></div><div><span>{labels.rate}</span><strong>{summary?.attendance_rate_pct == null ? '—' : `${summary.attendance_rate_pct.toFixed(2)}%`}</strong></div></div>
      <p className="attendance-report-note">{isAm ? 'መገኘት = ተገኝቷል + ዘግይቷል፤ በፈቃድ የቀሩ ከመጠኑ ይወገዳሉ። ይህ የተመዘገቡ መዝገቦችን ብቻ ይቆጥራል።' : 'Rate = (present + late) ÷ (recorded total − excused) × 100. Only recorded entries are counted; missing attendance is not inferred.'}</p>
    </div>
    <div className="student-form bulk-attendance-form"><h2>{labels.bulkTitle}</h2><div className="student-form-grid"><label>{labels.sectionScope}<select value={selectedSectionId} onChange={e => setSelectedSectionId(e.target.value)}><option value="">{labels.allStudents}</option>{sections.filter(section => section.status !== 'archived').map(section => <option key={section.section_id} value={section.section_id}>{section.class_level} {section.name} · {section.academic_year} · {section.branch_id}</option>)}</select></label></div><p className="attendance-report-note">{isAm ? 'ከዚህ ቀን መዝገብ የሌላቸው ተማሪዎች ብቻ ይታያሉ። ሴክሽን ከመረጡ በዚያ ሴክሽን የተመዘገቡ ተማሪዎች ብቻ ይጫናሉ።' : 'Only students without an attendance entry for the selected date are shown. Choose a section to limit the roster to currently enrolled students, then save the batch atomically.'}</p>
      {students.filter(student => !records.some(record => record.student_id === student.student_id)).length === 0 ? <p>{labels.bulkEmpty}</p> : <>
        <div className="bulk-attendance-list">{students.filter(student => !records.some(record => record.student_id === student.student_id)).map(student => <label className="bulk-attendance-row" key={student.student_id}><span><strong>{student.given_name} {student.middle_name ? `${student.middle_name} ` : ''}{student.family_name}</strong><small>{student.branch_id}</small></span><select aria-label={`${labels.status}: ${student.given_name} ${student.family_name}`} value={bulkStatuses[student.student_id] || 'present'} onChange={e => setBulkStatuses(previous => ({ ...previous, [student.student_id]: e.target.value as AttendanceRecord['status'] }))}><option value="present">{labels.present}</option><option value="absent">{labels.absent}</option><option value="late">{labels.late}</option><option value="excused">{labels.excused}</option></select></label>)}</div>
        <div className="form-actions"><button type="button" className="primary-button" disabled={bulkSaving || loading || !students.length} onClick={() => void submitBulk()}><Users size={15} /> {bulkSaving ? labels.saving : labels.bulkSubmit}</button></div>
      </>}
    </div>
    <form className="student-form" onSubmit={submit}><h2>{labels.record}</h2><div className="student-form-grid">
      <label>{labels.date}<input type="date" required value={date} onChange={e => setDate(e.target.value)} /></label>
      <label>{labels.student}<select required value={studentId} onChange={e => setStudentId(e.target.value)}><option value="">{labels.choose}</option>{students.map(s => <option key={s.student_id} value={s.student_id}>{s.given_name} {s.family_name} · {s.branch_id}</option>)}</select></label>
      <label>{labels.status}<select value={status} onChange={e => setStatus(e.target.value as AttendanceRecord['status'])}><option value="present">{labels.present}</option><option value="absent">{labels.absent}</option><option value="late">{labels.late}</option><option value="excused">{labels.excused}</option></select></label>
      <label className="full-field">{labels.note}<input maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></label>
    </div><div className="form-actions"><button type="submit" className="primary-button" disabled={saving || loading || !students.length}><Plus size={15} /> {saving ? labels.saving : labels.submit}</button></div></form>
    <div className="directory-toolbar"><div><strong>{records.length}</strong> {labels.records}</div><span>{labels.date}: {date}</span></div>
    <div className="student-table-wrap"><table className="student-table"><thead><tr><th>{labels.student}</th><th>{labels.date}</th><th>{labels.status}</th><th>{labels.note}</th><th>Actions</th></tr></thead><tbody>
      {loading ? <tr><td colSpan={5} className="table-message">{t.loading}</td></tr> : records.length === 0 ? <tr><td colSpan={5} className="table-message">{labels.empty}</td></tr> : records.map(record => <tr key={record.attendance_id}><td><strong>{studentName(record.student_id)}</strong></td><td>{record.attendance_date}</td><td><span className={`student-status attendance-${record.status}`}>{statusLabels[record.status]}</span></td><td>{record.note || '—'}</td><td><button className="secondary-button compact-button" onClick={() => { setCorrectionId(record.attendance_id); setCorrectionStatus(record.status); setCorrectionReason(''); }}>{labels.correction}</button></td></tr>)}
    </tbody></table></div>
    {correctionId && <form className="student-form" onSubmit={saveCorrection}><h2>{labels.correction}</h2><div className="student-form-grid"><label>{labels.status}<select value={correctionStatus} onChange={e => setCorrectionStatus(e.target.value as AttendanceRecord['status'])}><option value="present">{labels.present}</option><option value="absent">{labels.absent}</option><option value="late">{labels.late}</option><option value="excused">{labels.excused}</option></select></label><label className="full-field">{labels.reason}<input required minLength={3} maxLength={500} value={correctionReason} onChange={e => setCorrectionReason(e.target.value)} /></label></div><div className="form-actions"><button type="button" className="secondary-button" onClick={() => setCorrectionId('')}>{labels.cancel}</button><button type="submit" className="primary-button" disabled={saving}>{labels.saveCorrection}</button></div></form>}
  </section>;
}

function StatCard({ title, value, change, positive, note, icon, iconClass, spark }: { title: string; value: string; change: string; positive: boolean; note: string; icon: React.ReactNode; iconClass: string; spark: number[] }) {
  return <div className="stat-card"><div className="stat-top"><span>{title}</span><div className={`stat-icon ${iconClass}`}>{icon}</div></div><div className="stat-value">{value}</div><div className="stat-bottom"><span className={`change-pill ${positive ? 'positive' : 'negative'}`}>{positive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{change}</span><span className="stat-note">{note}</span><div className="sparkline">{spark.map((h, i) => <i key={i} style={{ height: `${h}%` }} />)}</div></div></div>;
}
function QuickAction({ icon, title, color, onClick }: { icon: React.ReactNode; title: string; color: string; onClick: () => void }) { return <button className="quick-action" onClick={onClick}><span className={`quick-icon ${color}`}>{icon}</span><span>{title}</span><ArrowUpRight size={15} className="quick-arrow" /></button>; }
type AssessmentRecord = { assessment_id: string; organization_id: string; branch_id: string; section_id?: string | null; subject: string; title: string; term: string; assessment_date: string | null; max_score: string; status: 'draft' | 'published'; published_at: string | null };
type AcademicSection = { section_id: string; branch_id: string; name: string; class_level: string; academic_year: string; status: string };
type AcademicStudent = { student_id: string; given_name: string; middle_name: string | null; family_name: string; branch_id: string };
type AcademicResult = { result_id: string; student_id: string; score: string; comment: string | null; given_name: string; middle_name: string | null; family_name: string; version?: number; locally_queued?: boolean };

function AcademicsPage({ t, isAm, actorId }: { t: typeof copy.en; isAm: boolean; actorId: string }) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const [assessments, setAssessments] = useState<AssessmentRecord[]>([]);
  const [students, setStudents] = useState<AcademicStudent[]>([]);
  const [sections, setSections] = useState<AcademicSection[]>([]);
  const [results, setResults] = useState<AcademicResult[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({ branch_id: 'main', section_id: '', subject: '', title: '', term: 'Term 1', assessment_date: new Date().toISOString().slice(0, 10), max_score: '100' });
  const [scores, setScores] = useState<Record<string, string>>({});
  const labels = isAm ? {
    title: 'የፈተናና ውጤት አስተዳደር', desc: 'ፈተና ይፍጠሩ፣ የተማሪዎችን ውጤት ያስገቡ፣ ከዚያ ያትሙ።', create: 'ፈተና ፍጠር', subject: 'ትምህርት', assessmentTitle: 'የፈተና ስም', term: 'ተርም', date: 'ቀን', branch: 'ቅርንጫፍ መለያ', section: 'ሴክሽን', allBranch: 'በቅርንጫፍ ደረጃ (ሴክሽን የለም)', max: 'ከፍተኛ ውጤት', save: 'ፈተና መዝግብ', list: 'የፈተና ዝርዝር', students: 'ተማሪዎች', score: 'ውጤት', comment: 'አስተያየት', saveScore: 'ውጤት መዝግብ', publish: 'ውጤት አትም', draft: 'ረቂቅ', published: 'ታትሟል', none: 'ፈተና አልተገኘም።', prototype: 'የልማት ፕሮቶታይፕ ብቻ። እውነተኛ የተማሪ መረጃ አያስገቡ።', locked: 'ከታተመ በኋላ ውጤት ማስተካከል አይቻልም።'
  } : {
    title: 'Assessments & results', desc: 'Create an assessment, enter student scores, then publish the results.', create: 'Create assessment', subject: 'Subject', assessmentTitle: 'Assessment title', term: 'Term / period', date: 'Assessment date', branch: 'Branch ID', section: 'Class / section', allBranch: 'Branch-wide (no section)', max: 'Maximum score', save: 'Save assessment', list: 'Assessments', students: 'Students', score: 'Score', comment: 'Comment', saveScore: 'Save score', publish: 'Publish results', draft: 'Draft', published: 'Published', none: 'No assessments yet.', prototype: 'Development prototype only. Do not enter real student information.', locked: 'Published results are locked against further edits.'
  };
  async function request(path: string, init?: RequestInit) {
    const response = await apiFetch(`${apiBase}${path}`, { ...init, headers: { 'X-Organization-ID': orgId, ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) } });
    if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
    return response.json();
  }
  async function loadAssessments(keepSelection = true) {
    setLoading(true); setError('');
    try {
      const data = await request(`/api/v1/academics/assessments?branch_id=${encodeURIComponent(form.branch_id)}`) as { items: AssessmentRecord[] };
      setAssessments(data.items);
      void saveSnapshot({ organizationId: orgId, actorId, key: `assessments:${form.branch_id}`, data: data.items }).catch(() => {});
      const nextId = keepSelection && data.items.some(a => a.assessment_id === selectedId) ? selectedId : data.items[0]?.assessment_id || '';
      setSelectedId(nextId);
    } catch (e) {
      try {
        const cached = await readSnapshot({ organizationId: orgId, actorId, key: `assessments:${form.branch_id}` });
        if (cached && Array.isArray(cached.data)) {
          setAssessments(cached.data as AssessmentRecord[]);
          const nextId = keepSelection && cached.data.some((a: AssessmentRecord) => a.assessment_id === selectedId) ? selectedId : cached.data[0]?.assessment_id || '';
          setSelectedId(nextId);
          setNotice(isAm ? 'የተቀመጠ የፈተና ዝርዝር ከኦፍላይን መሸጎጫ ተከፍቷል።' : 'Showing cached assessments; data may be stale.');
        } else setError(e instanceof Error ? e.message : t.apiError);
      } catch { setError(e instanceof Error ? e.message : t.apiError); }
    }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void loadAssessments(false);
    request('/api/v1/classrooms/sections').then(data => {
      const active = (data as { items: AcademicSection[] }).items.filter(s => s.status === 'active');
      setSections(active);
      void saveSnapshot({ organizationId: orgId, actorId, key: 'active-sections', data: active }).catch(() => {});
    }).catch(async () => {
      try {
        const cached = await readSnapshot({ organizationId: orgId, actorId, key: 'active-sections' });
        setSections(cached && Array.isArray(cached.data) ? cached.data as AcademicSection[] : []);
      } catch { setSections([]); }
    });
  }, [apiBase, orgId, actorId]);
  useEffect(() => {
    if (!selectedId) { setResults([]); setStudents([]); return; }
    let cancelled = false;
    const assessment = assessments.find(a => a.assessment_id === selectedId);
    const branchId = assessment?.branch_id || form.branch_id;
    const sectionId = assessment?.section_id;
    const rosterKey = `students:${branchId}:${sectionId || 'all'}`;
    const resultsKey = `results:${selectedId}`;
    Promise.all([
      request(`/api/v1/academics/assessments/${encodeURIComponent(selectedId)}/results`).then(async data => {
        const items = (data as { items: AcademicResult[] }).items;
        void saveSnapshot({ organizationId: orgId, actorId, key: resultsKey, data: items }).catch(() => {});
        return items;
      }).catch(async () => {
        const cached = await readSnapshot({ organizationId: orgId, actorId, key: resultsKey });
        if (!cached || !Array.isArray(cached.data)) throw new Error('No cached results are available for this assessment.');
        return cached.data as AcademicResult[];
      }),
      request(`/api/v1/academics/students?branch_id=${encodeURIComponent(branchId)}${sectionId ? `&section_id=${encodeURIComponent(sectionId)}` : ''}`).then(async data => {
        const items = (data as { items: AcademicStudent[] }).items;
        void saveSnapshot({ organizationId: orgId, actorId, key: rosterKey, data: items }).catch(() => {});
        return items;
      }).catch(async () => {
        const cached = await readSnapshot({ organizationId: orgId, actorId, key: rosterKey });
        if (!cached || !Array.isArray(cached.data)) throw new Error('No cached student roster is available. Open this assessment online once before using it offline.');
        return cached.data as AcademicStudent[];
      }),
    ]).then(async ([serverOrCachedResults, studentItems]) => {
      let visibleResults = serverOrCachedResults;
      try {
        const outboxRows = await listOutboxMutations({ organizationId: orgId, limit: 500 });
        visibleResults = mergePendingAssessmentResults(serverOrCachedResults, studentItems, outboxRows, selectedId, actorId) as AcademicResult[];
      } catch { /* Cached/server read data remains usable if outbox is unavailable. */ }
      if (!cancelled) {
        setResults(visibleResults);
        setStudents(studentItems);
        setScores(Object.fromEntries(visibleResults.map(result => [result.student_id, result.score])));
      }
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : t.apiError); });
    return () => { cancelled = true; };
  }, [selectedId, assessments, form.branch_id, apiBase, orgId, actorId]);
  async function createAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(''); setNotice('');
    try {
      const created = await request('/api/v1/academics/assessments', { method: 'POST', body: JSON.stringify({ ...form, section_id: form.section_id || null, assessment_date: form.assessment_date || null }) }) as AssessmentRecord;
      setNotice(isAm ? 'ፈተናው ተመዝግቧል።' : 'Assessment created.');
      await loadAssessments(false); setSelectedId(created.assessment_id);
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setSaving(false); }
  }
  async function saveScore(studentId: string) {
    const value = scores[studentId];
    if (value === undefined || value.trim() === '' || !selectedId) return;
    setSaving(true); setError(''); setNotice('');
    try {
      if (!navigator.onLine) {
        const cryptoApi = globalThis.crypto;
        if (!cryptoApi?.randomUUID) throw new Error(isAm ? 'ደህንነቱ የተጠበቀ መለያ ማመንጨት አልተቻለም።' : 'Secure mutation IDs are unavailable.');
        let deviceId = 'temporary-device-session';
        try {
          const saved = window.localStorage.getItem('school_device_id');
          if (saved) deviceId = saved;
          else { deviceId = cryptoApi.randomUUID(); window.localStorage.setItem('school_device_id', deviceId); }
        } catch { /* Session fallback is intentionally temporary. */ }
        const current = results.find(result => result.student_id === studentId);
        const entityId = current?.result_id || cryptoApi.randomUUID();
        const envelope = createMutationEnvelope({
          mutationId: cryptoApi.randomUUID(), organizationId: orgId, deviceId, actorId,
          entityType: 'draft_assessment_result', entityId,
          operation: current ? 'update' : 'create', baseVersion: current ? (current.version ?? 1) : null,
          payload: { assessment_id: selectedId, student_id: studentId, score: value, comment: current?.comment ?? null },
        });
        await enqueueMutation(envelope);
        const student = students.find(item => item.student_id === studentId);
        const queuedResult: AcademicResult = {
          result_id: entityId, student_id: studentId, score: value, comment: current?.comment ?? null,
          given_name: student?.given_name || '', middle_name: student?.middle_name ?? null,
          family_name: student?.family_name || '', version: current ? (current.version ?? 1) + 1 : 1,
        };
        setResults(previous => current ? previous.map(item => item.student_id === studentId ? queuedResult : item) : [...previous, queuedResult]);
        setNotice(isAm ? 'ውጤቱ በዚህ ኮምፒውተር በኦፍላይን ወረፋ ተቀምጧል። ከኢንተርኔት ጋር ሲገናኙ ያመሳስሉ።' : 'Score saved to this device’s offline queue. Sync when the connection returns.');
        return;
      }
      await request(`/api/v1/academics/assessments/${encodeURIComponent(selectedId)}/results`, { method: 'POST', body: JSON.stringify({ student_id: studentId, score: value }) });
      setNotice(isAm ? 'ውጤቱ ተመዝግቧል።' : 'Score saved.');
      const data = await request(`/api/v1/academics/assessments/${encodeURIComponent(selectedId)}/results`) as { items: AcademicResult[] };
      setResults(data.items);
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setSaving(false); }
  }
  async function publish() {
    if (!selectedId || !window.confirm(isAm ? 'ውጤቱን ማተም ይፈልጋሉ? ከታተመ በኋላ ማስተካከል አይቻልም።' : 'Publish and lock these results? Published results cannot be edited.')) return;
    setSaving(true); setError('');
    try { await request(`/api/v1/academics/assessments/${encodeURIComponent(selectedId)}/publish`, { method: 'POST' }); setNotice(isAm ? 'ውጤቱ ታትሟል።' : 'Results published and locked.'); await loadAssessments(); }
    catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setSaving(false); }
  }
  const selected = assessments.find(a => a.assessment_id === selectedId);
  const recorded = new Set(results.map(r => r.student_id));
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">{t.moduleReady}</div><h1>{labels.title}</h1><p>{labels.desc}</p></div><button className="secondary-button" onClick={() => void loadAssessments()}><RefreshCw size={15} /> {t.reload}</button></div>
    <div className="prototype-alert"><ShieldCheck size={17} /> {labels.prototype}</div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status">{notice}</div>}
    <form className="student-form" onSubmit={createAssessment}><h2>{labels.create}</h2><div className="student-form-grid">
      <label>{labels.subject}<input required maxLength={120} value={form.subject} onChange={e => setForm(v => ({ ...v, subject: e.target.value }))} /></label>
      <label>{labels.assessmentTitle}<input required maxLength={160} value={form.title} onChange={e => setForm(v => ({ ...v, title: e.target.value }))} /></label>
      <label>{labels.term}<input required maxLength={80} value={form.term} onChange={e => setForm(v => ({ ...v, term: e.target.value }))} /></label>
      <label>{labels.branch}<input required maxLength={64} value={form.branch_id} onChange={e => setForm(v => ({ ...v, branch_id: e.target.value, section_id: '' }))} /></label>
      <label>{labels.section}<select value={form.section_id} onChange={e => setForm(v => ({ ...v, section_id: e.target.value }))}><option value="">{labels.allBranch}</option>{sections.filter(s => s.branch_id === form.branch_id).map(s => <option key={s.section_id} value={s.section_id}>{s.class_level} — {s.name} · {s.academic_year}</option>)}</select></label>
      <label>{labels.date}<input type="date" value={form.assessment_date} onChange={e => setForm(v => ({ ...v, assessment_date: e.target.value }))} /></label>
      <label>{labels.max}<input required type="number" min="0.001" step="0.001" value={form.max_score} onChange={e => setForm(v => ({ ...v, max_score: e.target.value }))} /></label>
    </div><div className="form-actions"><button className="primary-button" type="submit" disabled={saving}>{labels.save}</button></div></form>
    <div className="student-form"><h2>{labels.list}</h2>{loading ? <p>{t.loading}</p> : assessments.length === 0 ? <p>{labels.none}</p> : <div className="assessment-list">{assessments.map(a => <button key={a.assessment_id} className={`assessment-option ${selectedId === a.assessment_id ? 'selected' : ''}`} onClick={() => setSelectedId(a.assessment_id)}><span><strong>{a.subject} — {a.title}</strong><small>{a.term} · {a.branch_id}{a.section_id ? ` · ${sections.find(s => s.section_id === a.section_id)?.class_level || ''} ${sections.find(s => s.section_id === a.section_id)?.name || ''}` : ''} · /{a.max_score}</small></span><span className={`student-status ${a.status === 'published' ? 'attendance-excused' : ''}`}>{a.status === 'published' ? labels.published : labels.draft}</span></button>)}</div>}</div>
    {selected && <div className="student-form"><div className="directory-heading"><div><h2>{selected.subject} — {selected.title}</h2><p>{labels.max}: {selected.max_score}. {selected.status === 'published' ? labels.locked : ''}</p></div>{selected.status === 'draft' && <button className="primary-button" disabled={saving || results.length === 0} onClick={() => void publish()}>{labels.publish}</button>}</div>
      <div className="student-table-wrap"><table className="student-table"><thead><tr><th>{labels.students}</th><th>{labels.score} / {selected.max_score}</th><th>{labels.comment}</th><th> </th></tr></thead><tbody>{students.length === 0 ? <tr><td colSpan={4} className="table-message">{t.noStudents}</td></tr> : students.map(student => { const result = results.find(r => r.student_id === student.student_id); return <tr key={student.student_id}><td><strong>{student.given_name} {student.middle_name ? `${student.middle_name} ` : ''}{student.family_name}</strong></td><td><input className="score-input" type="number" min="0" max={selected.max_score} step="0.001" value={scores[student.student_id] ?? ''} disabled={selected.status === 'published'} onChange={e => setScores(v => ({ ...v, [student.student_id]: e.target.value }))} /></td><td>{result?.comment || '—'}</td><td>{selected.status === 'draft' && <button className="secondary-button compact-button" disabled={saving || !scores[student.student_id]} onClick={() => void saveScore(student.student_id)}>{labels.saveScore}</button>}{result?.locally_queued ? <span className="student-status">{isAm ? 'በወረፋ ላይ' : 'Queued locally'}</span> : recorded.has(student.student_id) && <span className="student-status">Saved</span>}</td></tr>; })}</tbody></table></div>
    </div>}
  </section>;
}

type ReportAssessment = { assessment_id: string; subject: string; title: string; max_score: string; score: string | null; percentage: string | null; comment: string | null };
type StudentReportCard = { student: { student_id: string; given_name: string; middle_name: string | null; family_name: string; branch_id: string }; section: { section_id: string; section_name: string; class_level: string; academic_year: string }; term: string; assessments: ReportAssessment[]; summary: { published_assessment_count: number; scored_assessment_count: number; missing_score_count: number; total_score: string; total_max_score: string; percentage: string | null }; };

function ReportsPage({ t, isAm }: { t: typeof copy.en; isAm: boolean }) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const [sections, setSections] = useState<ClassroomSection[]>([]);
  const [students, setStudents] = useState<ClassroomStudent[]>([]);
  const [sectionId, setSectionId] = useState('');
  const [studentId, setStudentId] = useState('');
  const [term, setTerm] = useState('Term 1');
  const [report, setReport] = useState<StudentReportCard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const labels = isAm ? {
    title: 'የተማሪ ውጤት ሪፖርት', desc: 'የታተሙ የፈተና ውጤቶችን በተማሪ፣ ሴክሽንና ተርም ይመልከቱ።', exportCsv: 'CSV አውርድ', printPdf: 'አትም / PDF', section: 'ሴክሽን', chooseSection: 'ሴክሽን ይምረጡ', student: 'ተማሪ', chooseStudent: 'ተማሪ ይምረጡ', term: 'ተርም', load: 'ሪፖርት አሳይ', refresh: 'ሴክሽኖችን አድስ', subject: 'ትምህርት', assessment: 'ፈተና', score: 'ውጤት', percent: 'መቶኛ', total: 'ጠቅላላ ውጤት', scored: 'ውጤት የተመዘገበላቸው', missing: 'የጎደሉ ውጤቶች', none: 'የታተሙ ውጤቶች አልተገኙም።', prototype: t.prototypeWarning, noSections: 'ሴክሽን አልተገኘም።'
  } : {
    title: 'Student report card', desc: 'View published assessment results by student, section and term.', exportCsv: 'Export CSV', printPdf: 'Print / Save PDF', section: 'Section', chooseSection: 'Choose section', student: 'Student', chooseStudent: 'Choose student', term: 'Term', load: 'Load report card', refresh: 'Refresh sections', subject: 'Subject', assessment: 'Assessment', score: 'Score', percent: 'Percent', total: 'Total score', scored: 'Scored assessments', missing: 'Missing scores', none: 'No published results found for this term.', prototype: t.prototypeWarning, noSections: 'No sections found.'
  };
  async function request(path: string) {
    const response = await apiFetch(`${apiBase}${path}`, { headers: { 'X-Organization-ID': orgId } });
    if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
    return response.json();
  }
  async function loadSections() {
    setError('');
    try {
      const data = await request('/api/v1/classrooms/sections') as { items: ClassroomSection[] };
      setSections(data.items.filter(section => section.status !== 'archived'));
      if (!sectionId && data.items.length) setSectionId(data.items.find(section => section.status !== 'archived')?.section_id || '');
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
  }
  useEffect(() => { void loadSections(); }, [apiBase, orgId]);
  useEffect(() => {
    setStudents([]); setStudentId(''); setReport(null);
    if (!sectionId) return;
    let cancelled = false;
    void request(`/api/v1/classrooms/sections/${encodeURIComponent(sectionId)}/students`).then(data => {
      if (cancelled) return;
      const items = (data as { items: ClassroomStudent[] }).items;
      setStudents(items); setStudentId(items[0]?.student_id || '');
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : t.apiError); });
    return () => { cancelled = true; };
  }, [sectionId, apiBase, orgId]);
  async function loadReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!sectionId || !studentId || !term.trim()) return;
    setLoading(true); setError(''); setNotice(''); setReport(null);
    try {
      const data = await request(`/api/v1/academics/reports/students/${encodeURIComponent(studentId)}?section_id=${encodeURIComponent(sectionId)}&term=${encodeURIComponent(term.trim())}`) as StudentReportCard;
      setReport(data);
      if (data.summary.published_assessment_count === 0) setNotice(labels.none);
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setLoading(false); }
  }
  function exportReportCsv() {
    if (!report) return;
    const headers = isAm
      ? ['ተማሪ መለያ', 'ስም', 'ክፍል', 'ሴክሽን', 'የትምህርት ዓመት', 'ተርም', 'ትምህርት', 'ፈተና', 'ውጤት', 'ከ', 'መቶኛ', 'አስተያየት']
      : ['Student ID', 'Student name', 'Class', 'Section', 'Academic year', 'Term', 'Subject', 'Assessment', 'Score', 'Maximum score', 'Percentage', 'Comment'];
    const safeCell = (value: unknown) => {
      let text = value == null ? '' : String(value);
      // Prevent spreadsheet formula execution for values originating in user-entered fields.
      if (/^[\s]*[=+@\-]/.test(text)) text = `'${text}`;
      return `"${text.replace(/"/g, '""')}"`;
    };
    const studentName = [report.student.given_name, report.student.middle_name, report.student.family_name].filter(Boolean).join(' ');
    const rows = report.assessments.map(item => [report.student.student_id, studentName, report.section.class_level, report.section.section_name, report.section.academic_year, report.term, item.subject, item.title, item.score, item.max_score, item.percentage, item.comment]);
    if (rows.length === 0) rows.push([report.student.student_id, studentName, report.section.class_level, report.section.section_name, report.section.academic_year, report.term, '', '', '', '', '', '']);
    const csv = '\uFEFF' + [headers, ...rows].map(row => row.map(safeCell).join(',')).join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `report-card-${report.student.student_id}-${report.term.replace(/[^a-zA-Z0-9_-]+/g, '-')}.csv`;
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  }
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">{t.moduleReady}</div><h1>{labels.title}</h1><p>{labels.desc}</p></div><button className="secondary-button" onClick={() => void loadSections()}><RefreshCw size={15} /> {labels.refresh}</button></div>
    <div className="prototype-alert"><ShieldCheck size={18} /><span>{labels.prototype}</span></div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status">{notice}</div>}
    <form className="student-form" onSubmit={e => void loadReport(e)}>
      <div className="student-form-grid">
        <label>{labels.section}<select required value={sectionId} onChange={e => setSectionId(e.target.value)}><option value="">{labels.chooseSection}</option>{sections.map(section => <option key={section.section_id} value={section.section_id}>{section.class_level} {section.name} · {section.academic_year} · {section.branch_id}</option>)}</select></label>
        <label>{labels.student}<select required value={studentId} onChange={e => setStudentId(e.target.value)}><option value="">{labels.chooseStudent}</option>{students.map(student => <option key={student.student_id} value={student.student_id}>{student.given_name} {student.middle_name ? `${student.middle_name} ` : ''}{student.family_name}</option>)}</select></label>
        <label>{labels.term}<input required maxLength={80} value={term} onChange={e => setTerm(e.target.value)} /></label>
      </div>
      <div className="form-actions"><button className="primary-button" disabled={loading || !sectionId || !studentId || !term.trim()}>{loading ? t.loading : labels.load}</button></div>
    </form>
    {sections.length === 0 && !error && <div className="table-message">{labels.noSections}</div>}
    {report && <>
      <div className="panel report-summary-panel"><div className="panel-heading"><div><h2>{report.student.given_name} {report.student.middle_name ? `${report.student.middle_name} ` : ''}{report.student.family_name}</h2><p>{report.section.class_level} {report.section.section_name} · {report.section.academic_year} · {report.term}</p></div><span className="student-status">{report.summary.percentage === null ? '—' : `${report.summary.percentage}%`}</span></div>
        <div className="report-print-actions"><button type="button" className="secondary-button" onClick={exportReportCsv}><Download size={15} /> {labels.exportCsv}</button><button type="button" className="secondary-button" onClick={() => window.print()}><Printer size={15} /> {labels.printPdf}</button></div>
        <div className="stats-grid report-stats"><StatCard title={labels.total} value={`${report.summary.total_score} / ${report.summary.total_max_score}`} change="" positive note={labels.scored} icon={<BookOpen size={19} />} iconClass="blue" spark={[]} /><StatCard title={labels.scored} value={String(report.summary.scored_assessment_count)} change="" positive note={labels.missing} icon={<ClipboardList size={19} />} iconClass="mint" spark={[]} /><StatCard title={labels.missing} value={String(report.summary.missing_score_count)} change="" positive={report.summary.missing_score_count === 0} note={isAm ? 'ውጤት የሌላቸው ፈተናዎች' : 'Assessments without a score'} icon={<ShieldCheck size={19} />} iconClass="gold" spark={[]} /></div>
      </div>
      <div className="student-table-wrap"><table className="student-table"><thead><tr><th>{labels.subject}</th><th>{labels.assessment}</th><th>{labels.score}</th><th>{labels.percent}</th></tr></thead><tbody>{report.assessments.length === 0 ? <tr><td colSpan={4} className="table-message">{labels.none}</td></tr> : report.assessments.map(item => <tr key={item.assessment_id}><td>{item.subject}</td><td>{item.title}</td><td>{item.score === null ? '—' : `${item.score} / ${item.max_score}`}</td><td>{item.percentage === null ? '—' : `${item.percentage}%`}</td></tr>)}</tbody></table></div>
    </>}
  </section>;
}

type ClassroomYear = { year_id: string; name: string; start_date: string; end_date: string; status: string };
type ClassroomLevel = { level_id: string; name: string; sort_order: number };
type ClassroomSection = { section_id: string; branch_id: string; year_id: string; level_id: string; name: string; capacity: number | null; academic_year: string; class_level: string };
type ClassroomStudent = { student_id: string; given_name: string; middle_name?: string | null; family_name: string; branch_id: string; status: string };
type ClassroomEnrollment = { enrollment_id: string; student_id: string; section_id: string; status: string; enrolled_on: string; given_name: string; middle_name?: string | null; family_name: string; section_name: string; branch_id: string; class_level: string; academic_year: string };

function ClassroomsPage({ t, isAm }: { t: typeof copy.en; isAm: boolean }) {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const orgId = import.meta.env.VITE_DEMO_ORGANIZATION_ID || 'demo-organization';
  const today = new Date().toISOString().slice(0, 10);
  const [years, setYears] = useState<ClassroomYear[]>([]);
  const [levels, setLevels] = useState<ClassroomLevel[]>([]);
  const [sections, setSections] = useState<ClassroomSection[]>([]);
  const [students, setStudents] = useState<ClassroomStudent[]>([]);
  const [enrollments, setEnrollments] = useState<ClassroomEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [yearForm, setYearForm] = useState({ name: '2026/2027', start_date: '2026-09-01', end_date: '2027-06-30' });
  const [levelForm, setLevelForm] = useState({ name: '', sort_order: '1' });
  const [sectionForm, setSectionForm] = useState({ branch_id: 'main', year_id: '', level_id: '', name: 'A', capacity: '40' });
  const [enrollmentForm, setEnrollmentForm] = useState({ student_id: '', section_id: '', enrolled_on: today });
  const labels = isAm ? {
    title: 'ክፍሎችና የተማሪ ምዝገባ', desc: 'የትምህርት ዓመት፣ የክፍል ደረጃ፣ ሴክሽን ይፍጠሩ እና ተማሪዎችን ይመዝግቡ።', year: 'የትምህርት ዓመት', yearName: 'የዓመት ስም', start: 'መጀመሪያ ቀን', end: 'መጨረሻ ቀን', createYear: 'ዓመት ፍጠር', levels: 'የክፍል ደረጃዎች', levelName: 'የክፍል ስም (ለምሳሌ Grade 1)', order: 'ቅደም ተከተል', createLevel: 'ክፍል ደረጃ ጨምር', sections: 'ሴክሽኖች', branch: 'የቅርንጫፍ መለያ', chooseYear: 'ዓመት ይምረጡ', chooseLevel: 'ክፍል ይምረጡ', sectionName: 'ሴክሽን (ለምሳሌ A)', capacity: 'የተማሪ አቅም', createSection: 'ሴክሽን ፍጠር', enroll: 'ተማሪ መመዝገብ', student: 'ተማሪ', chooseStudent: 'ተማሪ ይምረጡ', chooseSection: 'ሴክሽን ይምረጡ', date: 'የምዝገባ ቀን', enrollButton: 'ተመዝግብ', roster: 'የተመዘገቡ ተማሪዎች', class: 'ክፍል', section: 'ሴክሽን', status: 'ሁኔታ', none: 'ምንም መዝገብ የለም።', refresh: 'እንደገና ጫን', prototype: t.prototypeWarning, savedYear: 'የትምህርት ዓመት ተፈጥሯል።', savedLevel: 'የክፍል ደረጃ ተፈጥሯል።', savedSection: 'ሴክሽን ተፈጥሯል።', savedEnrollment: 'ተማሪው ተመዝግቧል።'
  } : {
    title: 'Classes & enrollment', desc: 'Create academic years and grade levels, set up branch sections, then enroll students.', year: 'Academic years', yearName: 'Academic year name', start: 'Start date', end: 'End date', createYear: 'Create year', levels: 'Grade levels', levelName: 'Grade name (e.g. Grade 1)', order: 'Sort order', createLevel: 'Add grade level', sections: 'Sections', branch: 'Branch ID', chooseYear: 'Choose academic year', chooseLevel: 'Choose grade level', sectionName: 'Section name (e.g. A)', capacity: 'Student capacity', createSection: 'Create section', enroll: 'Enroll a student', student: 'Student', chooseStudent: 'Choose student', chooseSection: 'Choose section', date: 'Enrollment date', enrollButton: 'Enroll student', roster: 'Enrolled students', class: 'Grade', section: 'Section', status: 'Status', none: 'No records yet.', refresh: 'Refresh', prototype: t.prototypeWarning, savedYear: 'Academic year created.', savedLevel: 'Grade level created.', savedSection: 'Section created.', savedEnrollment: 'Student enrolled.'
  };
  async function request(path: string, init?: RequestInit) {
    const response = await apiFetch(`${apiBase}${path}`, { ...init, headers: { 'X-Organization-ID': orgId, ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) } });
    if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail || `API returned ${response.status}`); }
    return response.json();
  }
  async function load() {
    setLoading(true); setError('');
    try {
      const [yearData, levelData, sectionData, studentData, enrollmentData] = await Promise.all([
        request('/api/v1/classrooms/academic-years') as Promise<{ items: ClassroomYear[] }>,
        request('/api/v1/classrooms/class-levels') as Promise<{ items: ClassroomLevel[] }>,
        request('/api/v1/classrooms/sections') as Promise<{ items: ClassroomSection[] }>,
        request('/api/v1/students?limit=500') as Promise<{ items: ClassroomStudent[] }>,
        request('/api/v1/classrooms/enrollments') as Promise<{ items: ClassroomEnrollment[] }>,
      ]);
      setYears(yearData.items); setLevels(levelData.items); setSections(sectionData.items); setStudents(studentData.items); setEnrollments(enrollmentData.items);
      setSectionForm(v => ({ ...v, year_id: v.year_id || yearData.items[0]?.year_id || '', level_id: v.level_id || levelData.items[0]?.level_id || '' }));
      setEnrollmentForm(v => ({ ...v, student_id: v.student_id || studentData.items[0]?.student_id || '', section_id: v.section_id || sectionData.items[0]?.section_id || '' }));
    } catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [apiBase, orgId]);
  async function submit(event: FormEvent<HTMLFormElement>, path: string, body: Record<string, unknown>, success: string, reset?: () => void) {
    event.preventDefault(); setSaving(true); setError(''); setNotice('');
    try { await request(path, { method: 'POST', body: JSON.stringify(body) }); setNotice(success); reset?.(); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : t.apiError); }
    finally { setSaving(false); }
  }
  return <section className="student-directory">
    <div className="directory-heading"><div><div className="eyebrow">{t.moduleReady}</div><h1>{labels.title}</h1><p>{labels.desc}</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} /> {labels.refresh}</button></div>
    <div className="prototype-alert"><ShieldCheck size={18} /><span>{labels.prototype}</span></div>
    {error && <div className="api-error" role="alert">{error}</div>}{notice && <div className="api-success" role="status"><CheckCircle2 size={17} />{notice}</div>}
    <div className="classroom-grid">
      <form className="student-form" onSubmit={e => void submit(e, '/api/v1/classrooms/academic-years', yearForm, labels.savedYear, () => setYearForm({ name: '', start_date: '', end_date: '' }))}>
        <h2>{labels.year}</h2><div className="student-form-grid"><label className="full-field">{labels.yearName}<input required value={yearForm.name} onChange={e => setYearForm(v => ({ ...v, name: e.target.value }))} /></label><label>{labels.start}<input type="date" required value={yearForm.start_date} onChange={e => setYearForm(v => ({ ...v, start_date: e.target.value }))} /></label><label>{labels.end}<input type="date" required min={yearForm.start_date || undefined} value={yearForm.end_date} onChange={e => setYearForm(v => ({ ...v, end_date: e.target.value }))} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving}>{labels.createYear}</button></div>
      </form>
      <form className="student-form" onSubmit={e => void submit(e, '/api/v1/classrooms/class-levels', { name: levelForm.name, sort_order: Number(levelForm.sort_order) }, labels.savedLevel, () => setLevelForm({ name: '', sort_order: '1' }))}>
        <h2>{labels.levels}</h2><div className="student-form-grid"><label className="full-field">{labels.levelName}<input required maxLength={80} value={levelForm.name} onChange={e => setLevelForm(v => ({ ...v, name: e.target.value }))} /></label><label>{labels.order}<input type="number" min="0" max="10000" required value={levelForm.sort_order} onChange={e => setLevelForm(v => ({ ...v, sort_order: e.target.value }))} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving}>{labels.createLevel}</button></div>
      </form>
      <form className="student-form" onSubmit={e => void submit(e, '/api/v1/classrooms/sections', { ...sectionForm, capacity: sectionForm.capacity ? Number(sectionForm.capacity) : null }, labels.savedSection, () => setSectionForm(v => ({ ...v, name: '' })))}>
        <h2>{labels.sections}</h2><div className="student-form-grid"><label>{labels.branch}<input required value={sectionForm.branch_id} onChange={e => setSectionForm(v => ({ ...v, branch_id: e.target.value }))} /></label><label>{labels.chooseYear}<select required value={sectionForm.year_id} onChange={e => setSectionForm(v => ({ ...v, year_id: e.target.value }))}><option value="">—</option>{years.map(y => <option key={y.year_id} value={y.year_id}>{y.name}</option>)}</select></label><label>{labels.chooseLevel}<select required value={sectionForm.level_id} onChange={e => setSectionForm(v => ({ ...v, level_id: e.target.value }))}><option value="">—</option>{levels.map(l => <option key={l.level_id} value={l.level_id}>{l.name}</option>)}</select></label><label>{labels.sectionName}<input required value={sectionForm.name} onChange={e => setSectionForm(v => ({ ...v, name: e.target.value }))} /></label><label>{labels.capacity}<input type="number" min="1" max="1000" value={sectionForm.capacity} onChange={e => setSectionForm(v => ({ ...v, capacity: e.target.value }))} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving || !years.length || !levels.length}>{labels.createSection}</button></div>
      </form>
      <form className="student-form" onSubmit={e => void submit(e, '/api/v1/classrooms/enrollments', enrollmentForm, labels.savedEnrollment)}>
        <h2>{labels.enroll}</h2><div className="student-form-grid"><label className="full-field">{labels.student}<select required value={enrollmentForm.student_id} onChange={e => setEnrollmentForm(v => ({ ...v, student_id: e.target.value }))}><option value="">{labels.chooseStudent}</option>{students.filter(s => s.status === 'active').map(s => <option key={s.student_id} value={s.student_id}>{s.given_name} {s.middle_name || ''} {s.family_name} · {s.branch_id}</option>)}</select></label><label className="full-field">{labels.chooseSection}<select required value={enrollmentForm.section_id} onChange={e => setEnrollmentForm(v => ({ ...v, section_id: e.target.value }))}><option value="">{labels.chooseSection}</option>{sections.map(s => <option key={s.section_id} value={s.section_id}>{s.class_level} — {s.name} · {s.academic_year} · {s.branch_id}</option>)}</select></label><label>{labels.date}<input type="date" required value={enrollmentForm.enrolled_on} onChange={e => setEnrollmentForm(v => ({ ...v, enrolled_on: e.target.value }))} /></label></div><div className="form-actions"><button className="primary-button" disabled={saving || !students.length || !sections.length}>{labels.enrollButton}</button></div>
      </form>
    </div>
    <div className="student-form"><div className="directory-toolbar"><span>{labels.roster}</span><strong>{enrollments.length} {t.totalRecords}</strong></div><div className="student-table-wrap"><table className="student-table"><thead><tr><th>{labels.student}</th><th>{labels.class}</th><th>{labels.section}</th><th>{labels.branch}</th><th>{labels.year}</th><th>{labels.date}</th><th>{labels.status}</th></tr></thead><tbody>{loading ? <tr><td colSpan={8} className="table-message">{t.loading}</td></tr> : enrollments.length === 0 ? <tr><td colSpan={7} className="table-message">{labels.none}</td></tr> : enrollments.map(e => <tr key={e.enrollment_id}><td><strong>{e.given_name} {e.middle_name ? `${e.middle_name} ` : ''}{e.family_name}</strong></td><td>{e.class_level}</td><td>{e.section_name}</td><td>{e.branch_id}</td><td>{e.academic_year}</td><td>{e.enrolled_on}</td><td><span className="student-status">{e.status}</span></td></tr>)}</tbody></table></div></div>
  </section>;
}

function ModulePage({ page, t, pageName, onDashboard, titleKey, descKey }: { page: Page; t: typeof copy.en; pageName: string; onDashboard: () => void; titleKey?: keyof typeof copy.en; descKey?: keyof typeof copy.en }) {
  const Icon = nav.find(n => n.id === page)?.icon ?? LayoutDashboard;
  return <div className="module-page"><div className="eyebrow">{t.moduleReady}</div><div className="module-icon"><Icon size={27} /></div><h1>{titleKey ? t[titleKey] : pageName}</h1><p>{descKey ? t[descKey] : t.pageIntro}</p><div className="module-notice"><ShieldCheck size={19} /><div><strong>{t.demo}</strong><span>{t.pageIntro}</span></div></div><div className="module-placeholder"><div className="placeholder-lines"><i /><i /><i /><i /></div><div className="placeholder-table"><div /><div /><div /><div /><div /><div /></div><span>{t.chooseModule}</span></div><button className="primary-button" onClick={onDashboard}><LayoutDashboard size={16} /> {t.dashboard}</button></div>;
}

export default App;
