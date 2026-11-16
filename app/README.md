# LiveTeach student app (Flutter, white-label)

Screens (final "Video Call" design): Login → OTP → Live Class (save-notes popup) → My Library → Pay Now → Payment successful.
The app is in English; the AI teacher answers in whatever language the student uses.

## Make a teacher's app
Edit `assets/teacher/teacher.json` (teacher id, app name, teacher name, subject, accent colour) and replace
`assets/teacher/avatar.jpg`. No code changes.

## Get the APK
Every push to `main` builds it on GitHub: **Actions → Build Android APK → latest run → Artifacts → liveteach-apk**.
Without a backend URL the app runs in **demo mode** (offline sample answers, any OTP works).
To connect a server: Actions → Build Android APK → Run workflow → enter the backend URL
(or set the repository variable `API_BASE_URL`).

## Run locally
```bash
flutter create --platforms=android --org com.durina.liveteach --project-name liveteach .   # first time only
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000     # Android emulator → local backend
```
