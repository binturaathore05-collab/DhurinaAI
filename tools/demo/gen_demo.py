import base64
src=open('../../backend/app/static/admin.html').read()
img="data:image/jpeg;base64,"+base64.b64encode(open('../../app/assets/teacher/avatar.jpg','rb').read()).decode()
s=src.replace('/teachers/${encodeURIComponent(t.id)}/avatar','${avatarUrl(t.id)}')
s=s.replace('<title>LiveTeach · Dhurina Admin</title>','<title>LiveTeach Admin – Demo</title>')
mock=open('demo_mock.js').read().replace('__IMG__', img)
s=s.replace("let KEY = (() => { try { return sessionStorage.getItem('adminToken') || ''; } catch { return ''; } })();", mock + "\nlet KEY = '';")
s=s.replace('''async function api(method, path, body) {
  const res = await fetch(''','''async function api(method, path, body) {
  return DEMO(method, path, body);
  const res = await fetch(''')
s=s.replace('<div id="app"></div>','<div style="background:#FEF3C7;color:#78350F;text-align:center;padding:8px 12px;font-size:13px;font-weight:600">Demo: sample data, nothing is saved. Demo login: type any email and any password.</div>\n<div id="app"></div>')
s=s.replace("Demo login: type any email and any password.","Demo login: type any email and any password.")
assert "return DEMO(" in s and "let KEY = '';" in s
open('out/admin-demo.html','w').write(s)
print("ok", len(s))
