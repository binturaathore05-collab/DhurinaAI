
// ================= DEMO MODE: no server; sample data lives in this page =================
const AVATARS = { subhash: "__IMG__" };
const avatarUrl = (id) => AVATARS[id] || '';
const DEMO_USER = { email: 'owner@dhurina.in', logins: [] };
const DEMO = (() => {
  const now = Date.now() / 1000, DAY = 86400;
  const settings = {
    company: { name: 'Dhurina Ventures Pvt. Ltd.', address: '', gstin: '', pan: '', linked_account: 'acc_DHURINA_DEMO' },
    defaults: { platform_percent: 20, demo_questions: 3, grace_days: 2, grace_questions: 3, renew_reminder_days: 3 },
    ai: { trusted_sites: ['pib.gov.in', 'india.gov.in', 'ncert.nic.in'], blocked_topics: ['politics', 'adult content'] },
    legal: { privacy_url: '', terms_url: '' } };
  const CHECK = [['consent','Teacher consent form signed'],['play_console','Play Console account (teacher’s own)'],['razorpay','Razorpay account + Route linked'],['content','Notes & YouTube connected (teacher dashboard)'],['published','Closed testing → production']];
  const teachers = {
    subhash: { id: 'subhash', name: 'Subhash Sir', subject: 'Rajasthan GK, History, Geography', app_name: 'Subhash Sir AI', brand_color: '#2DD4BF', status: 'live', platform_percent: 20,
      monthly_price: 499, yearly_price: 3999, demo_questions: null, grace_days: null, grace_questions: null, razorpay_key_id: 'rzp_live_demo', secret: '••••4f2a', webhook: '',
      teacher_phone: '', teacher_email: '', checklist: { consent: true, play_console: true, razorpay: true }, students: 12, active: 7,
      months: [24950, 34930, 29940, 44910, 39920, 49900].map((r) => r * 100), builds: [{ n: 2, s: 'success', t: now - 4 * DAY }, { n: 1, s: 'success', t: now - 9 * DAY }] },
    meena: { id: 'meena', name: 'Meena Ma’am', subject: 'Science', app_name: 'Meena Ma’am AI', brand_color: '#F472B6', status: 'building', platform_percent: 25,
      monthly_price: 399, yearly_price: 2999, razorpay_key_id: '', secret: '', webhook: '', checklist: { consent: true }, students: 0, active: 0, months: [0,0,0,0,0,0], builds: [{ n: 1, s: 'running', t: now - 600 }] },
    rakesh: { id: 'rakesh', name: 'Rakesh Sir', subject: 'Maths', app_name: 'Rakesh Sir AI', brand_color: '#60A5FA', status: 'draft', platform_percent: 30,
      monthly_price: null, yearly_price: null, razorpay_key_id: '', secret: '', webhook: '', checklist: {}, students: 0, active: 0, months: [0,0,0,0,0,0], builds: [] },
  };
  const monthLabels = [...Array(6)].map((_, i) => { const d = new Date(); d.setMonth(d.getMonth() - 5 + i); return d.toLocaleString('en', { month: 'short' }); });
  const pct = (t) => t.platform_percent ?? settings.defaults.platform_percent;
  const money = (total, p) => ({ total_paise: total, platform_paise: Math.round(total * p / 100), teacher_paise: total - Math.round(total * p / 100) });
  const detail = (t) => ({ ...t, subjects: (t.subject || '').split(',').map((x) => x.trim()).filter(Boolean), has_avatar: !!AVATARS[t.id], effective_platform_percent: pct(t), teacher_percent: 100 - pct(t),
    razorpay_key_secret: t.secret, razorpay_webhook_secret: t.webhook, active_plans: t.active,
    checklist: CHECK.map(([key, label]) => ({ key, label, done: !!t.checklist[key] })),
    this_month: money(t.months[5], pct(t)), months: t.months.map((v, i) => ({ label: monthLabels[i], total_paise: v })) });
  const err = (m) => { const e = new Error(m); e.status = 400; throw e; };
  function save(data, creating) {
    const id = String(data.id || '').trim().toLowerCase();
    if (!/^[a-z][a-z0-9-]{1,30}$/.test(id)) err('Teacher id: lower-case letters, numbers and - only, starting with a letter');
    if (creating && teachers[id]) err(`A teacher with id '${id}' already exists`);
    if (!String(data.name || '').trim()) err('Teacher name is required');
    const p = data.platform_percent === '' || data.platform_percent == null ? null : Number(data.platform_percent);
    if (p != null && (p < 0 || p > 100)) err('Dhurina share must be between 0 and 100');
    const old = teachers[id] || { status: 'draft', checklist: {}, students: 0, active: 0, months: [0,0,0,0,0,0], builds: [], secret: '', webhook: '' };
    const num = (v) => v === '' || v == null ? null : Number(v);
    teachers[id] = { ...old, id, name: data.name.trim(), subject: Array.isArray(data.subjects) ? [...new Set(data.subjects)].join(', ') : (data.subject || ''), app_name: data.app_name || data.name.trim() + ' AI',
      brand_color: data.brand_color || '#2DD4BF', platform_percent: p, monthly_price: num(data.monthly_price) ?? old.monthly_price ?? null,
      yearly_price: num(data.yearly_price) ?? old.yearly_price ?? null, demo_questions: num(data.demo_questions), grace_days: num(data.grace_days),
      grace_questions: num(data.grace_questions), razorpay_key_id: data.razorpay_key_id || old.razorpay_key_id || '',
      secret: data.razorpay_key_secret ? '••••' + data.razorpay_key_secret.slice(-4) : old.secret,
      webhook: data.razorpay_webhook_secret ? '••••' + data.razorpay_webhook_secret.slice(-4) : old.webhook,
      teacher_phone: data.teacher_phone || '', teacher_email: data.teacher_email || '' };
    if (data.photo_base64) AVATARS[id] = data.photo_base64;
    return detail(teachers[id]);
  }

  // ---- demo sales: ~2,500 payments over the last 11 months ----
  const PAYS = (() => { let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const names = ['Rohit', 'Pooja', 'Aman', 'Neha', 'Student', 'Vikram', 'Kavita', 'Sunil', 'Priya', 'Arjun'];
    const cfg = { subhash: [900, 499, 3999], meena: [500, 399, 2999], rakesh: [300, 299, 1999] }; const out = []; let n = 0, sid = 0;
    for (const [tid, [count, mp, yp]] of Object.entries(cfg)) for (let i = 0; i < count; i++) { sid++; const yearly = rnd() < 0.2;
      const first = Date.now() - rnd() * 330 * DAY * 1000; const times = yearly ? 1 : [1, 1, 2, 3][Math.floor(rnd() * 4)];
      const name = names[Math.floor(rnd() * 10)], phone = '•••••• ' + String(1000 + Math.floor(rnd() * 8999));
      for (let k = 0; k < times; k++) { const at = first + k * 30 * DAY * 1000; if (at > Date.now()) break; n++;
        out.push({ tid, sid, name, phone, at, plan: yearly ? 'Yearly' : 'Monthly', amount: (yearly ? yp : mp) * 100, renewal: k > 0, id: 'pay_' + String(n).padStart(6, '0') }); } }
    return out.sort((a, b) => b.at - a.at); })();
  function rangeOf(P) { const s = new Date(P.date_from + 'T00:00:00'), e = new Date(P.date_to + 'T00:00:00'); if (isNaN(s) || isNaN(e) || e < s) err("'To' date is before 'From' date");
    return [s.getTime(), e.getTime() + DAY * 1000]; }
  const fmtD = (d) => String(d.getDate()).padStart(2, '0') + ' ' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()] + ' ' + d.getFullYear();
  function selectPays(P) { const [s, e] = rangeOf(P); return PAYS.filter((p) => p.at >= s && p.at < e && (!P.teacher || p.tid === P.teacher)); }
  const pctOf = (tid) => teachers[tid] ? (teachers[tid].platform_percent ?? 20) : 20;

  return async function (method, path, body) {
    await new Promise((r) => setTimeout(r, 150));
    let m;
    const U = new URL('http://x' + path), P = Object.fromEntries(U.searchParams);
    if (U.pathname === '/reports') { const list = selectPays(P); const by = {};
      for (const t of Object.values(teachers)) by[t.id] = { id: t.id, name: t.name, status: t.status, split_teacher: 100 - pctOf(t.id), split_dhurina: pctOf(t.id),
        total_students: new Set(PAYS.filter((p) => p.tid === t.id).map((p) => p.sid)).size, paying: new Set(), subscriptions: 0, renewals: 0, gross_paise: 0, dhurina_paise: 0 };
      const months = {}; let gross = 0, du = 0, ren = 0; const studs = new Set(), tset = new Set();
      for (const p of list) { const cut = Math.round(p.amount * pctOf(p.tid) / 100), b = by[p.tid]; b.subscriptions++; b.renewals += p.renewal; b.gross_paise += p.amount; b.dhurina_paise += cut; b.paying.add(p.sid);
        gross += p.amount; du += cut; ren += p.renewal; studs.add(p.tid + p.sid); tset.add(p.tid);
        const d = new Date(p.at), k = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); months[k] = months[k] || { s: 0, g: 0, d: 0 }; months[k].s++; months[k].g += p.amount; months[k].d += cut; }
      let rows = Object.values(by).map((b) => ({ ...b, paying_students: b.paying.size, new: b.subscriptions - b.renewals, teacher_paise: b.gross_paise - b.dhurina_paise, share_of_sales: gross ? Math.round(b.gross_paise * 1000 / gross) / 10 : 0 }));
      if (P.teacher) rows = rows.filter((r) => r.id === P.teacher);
      const key = { name: (a, b) => a.name.localeCompare(b.name), students: (a, b) => b.paying_students - a.paying_students, dhurina: (a, b) => b.dhurina_paise - a.dhurina_paise }[P.sort] || ((a, b) => b.gross_paise - a.gross_paise);
      rows.sort(key);
      const monthly = []; const [s, e] = rangeOf(P); const c = new Date(s); c.setDate(1);
      while (c.getTime() < e) { const k = c.getFullYear() + '-' + String(c.getMonth() + 1).padStart(2, '0'), v = months[k] || { s: 0, g: 0, d: 0 };
        monthly.push({ month: k, label: c.toLocaleString('en', { month: 'short', year: 'numeric' }), subscriptions: v.s, gross_paise: v.g, dhurina_paise: v.d }); c.setMonth(c.getMonth() + 1); }
      return { period_from: fmtD(new Date(s)), period_to: fmtD(new Date(e - 1)), by_teacher: rows, monthly,
        summary: { subscriptions: list.length, renewals: ren, new: list.length - ren, paying_students: studs.size, selling_teachers: tset.size, gross_paise: gross, dhurina_paise: du, teachers_paise: gross - du,
          teachers_percent: gross ? Math.round((gross - du) * 10000 / gross) / 100 : null, dhurina_percent: gross ? Math.round(du * 10000 / gross) / 100 : null } }; }
    if (U.pathname === '/reports/payments') { const q = (P.q || '').toLowerCase(); const list = selectPays(P).filter((p) => !q || (teachers[p.tid].name + ' ' + p.name + ' ' + p.phone.slice(-4) + ' ' + p.id).toLowerCase().includes(q));
      const off = +(P.offset || 0), lim = +(P.limit || 50);
      return { total: list.length, items: list.slice(off, off + lim).map((p) => { const pct = pctOf(p.tid), cut = Math.round(p.amount * pct / 100), d = new Date(p.at);
        return { date: d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0') + ' ' + d.toTimeString().slice(0, 5), payment_id: p.id, teacher: teachers[p.tid].name, student: p.name, phone: p.phone, plan: p.plan,
          type: p.renewal ? 'Renewal' : 'New', amount_paise: p.amount, dhurina_percent: pct, dhurina_paise: cut, teacher_percent: 100 - pct, teacher_paise: p.amount - cut }; }) }; }
    if (path === '/overview') {
      const list = Object.values(teachers);
      const tm = list.reduce((a, t) => { const x = money(t.months[5], pct(t)); a.total_paise += x.total_paise; a.platform_paise += x.platform_paise; return a; }, { total_paise: 0, platform_paise: 0 });
      return { overview: { teachers: list.length, live: list.filter((t) => t.status === 'live').length, students: list.reduce((a, t) => a + t.students, 0),
          active_plans: list.reduce((a, t) => a + t.active, 0), this_month: tm },
        teachers: list.map((t) => ({ id: t.id, name: t.name, subject: t.subject, status: t.status, has_avatar: !!AVATARS[t.id], platform_percent: pct(t),
          teacher_percent: 100 - pct(t), students: t.students, active_plans: t.active, this_month: money(t.months[5], pct(t)) })) };
    }
    if (path === '/login') { if (!String(body.email || '').includes('@') || !body.password) err('Enter your email and password'); DEMO_USER.email = body.email.toLowerCase();
      DEMO_USER.logins.unshift({ at: new Date().toISOString().replace('T', ' ').slice(0, 19), ip: 'demo', success: 1 }); return { token: 'demo-token', name: 'Owner', email: DEMO_USER.email, role: 'owner' }; }
    if (path === '/me') return { email: DEMO_USER.email, name: 'Owner', role: 'owner', recent_logins: DEMO_USER.logins.slice(0, 5) };
    if (path === '/password') { if (!body.current_password) err('Current password is wrong'); if ((body.new_password || '').length < 8) err('Password must be at least 8 characters and mix letters and numbers'); return { changed: true }; }
    if (path === '/settings') { if (method === 'PUT') { if (body.defaults && (body.defaults.platform_percent < 0 || body.defaults.platform_percent > 100)) err('Default split must be between 0 and 100');
      for (const k in body) Object.assign(settings[k], body[k]); } return JSON.parse(JSON.stringify(settings)); }
    if (path === '/teachers' && method === 'POST') return save(body, true);
    if ((m = path.match(/^\/teachers\/([^/]+)$/))) { const id = decodeURIComponent(m[1]); if (!teachers[id]) err('Teacher not found');
      return method === 'PUT' ? save({ ...body, id }, false) : detail(teachers[id]); }
    if ((m = path.match(/^\/teachers\/([^/]+)\/checklist$/))) { const t = teachers[decodeURIComponent(m[1])]; t.checklist[body.item] = !!body.done;
      if (t.checklist.published) t.status = 'live'; return detail(t); }
    if ((m = path.match(/^\/teachers\/([^/]+)\/build$/))) { const t = teachers[decodeURIComponent(m[1])];
      t.builds.unshift({ n: (t.builds[0]?.n || 0) + 1, s: 'running', t: Date.now() / 1000 }); if (t.status === 'draft') t.status = 'building';
      setTimeout(() => { t.builds[0].s = 'success'; if (location.hash.startsWith('#/t/')) loadBuilds(t.id); }, 6000); return { started: true }; }
    if ((m = path.match(/^\/teachers\/([^/]+)\/builds$/))) { const t = teachers[decodeURIComponent(m[1])];
      return t.builds.map((b) => ({ id: b.n, number: b.n, status: b.s === 'running' ? 'in_progress' : 'completed', conclusion: b.s === 'running' ? null : b.s,
        created_at: new Date(b.t * 1000).toISOString(), url: '#demo-apk' })); }
    err('Not found');
  };
})();

