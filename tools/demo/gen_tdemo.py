import base64
s=open('../../backend/app/static/teacher.html').read()
img="data:image/jpeg;base64,"+base64.b64encode(open('../../app/assets/teacher/avatar.jpg','rb').read()).decode()
s=s.replace('<title>LiveTeach · Teacher Dashboard</title>','<title>LiveTeach Teacher Dashboard – Demo</title>')
s=s.replace('<div id="app"></div>','<div style="background:#FEF3C7;color:#78350F;text-align:center;padding:8px 12px;font-size:13px;font-weight:600">Demo: sample data, nothing is saved. Log in with any email and password.</div>\n<div id="app"></div>\n<script>window.__AVATAR = "'+img+'";</script>')
open('out/teacher-demo.html','w').write(s)
