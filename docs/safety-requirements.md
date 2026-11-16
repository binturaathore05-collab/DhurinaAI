# Safety & control requirements (from the owner)

Points the owner asked to **record now and build later**. Nothing here is built until the owner says so.
Each point: what it is, the simple plan, where it touches, and its status.

Priority: **P1** = before launch · **P2** = before server go-live · **P3** = after launch.

---

## Already in place
- Admin login: email + password, lock for 15 min after 5 wrong tries, 12-hour sessions, login history.
- Teacher panel never shows Dhurina's % or amount.
- Student phone numbers are masked everywhere (•••••• 1234).
- Razorpay keys/secrets stored encrypted; never in code.
- A confirm popup before every delete / reject / disconnect / money change (app, teacher panel, admin).

---

## S1 · Block or remove a teacher, block a student — P1 · status: **noted, not started**
Asked on 17 Nov 2026: "किसी टीचर को हटाना, डिलीट करना या ब्लॉक करना, या किसी स्टूडेंट को ब्लॉक करना — स्ट्रक्चर तैयार करना, अभी मत करो।"

Plan to propose (to be confirmed by the owner before building):

**Teacher: three levels, softest first**
| Action | What happens | Students | Money | Undo |
|---|---|---|---|---|
| Pause | App shows "Classes paused, back soon"; teacher can still log in to the panel | Keep access to notes; no new questions; plan days kept | No new payments | Yes, one click |
| Block | Teacher can't log in; app shows "This app is no longer available"; no new sign-ups | Notes stay downloadable; refund / move-to-another-teacher decided by admin | No new payments; earlier payments and reports stay | Yes |
| Remove | Only after Block + a waiting period (e.g. 30 days); teacher data archived, not erased | Students informed in the app | All payment records kept for accounts/GST (never deleted) | Restore from archive within the waiting period |

**Student**
| Action | What happens | Undo |
|---|---|---|
| Block | Can't log in or ask; sees "Your account is blocked, contact support"; no new payments | Yes |
| Remove (on student's own request too) | Personal data (phone, name, notes) erased; payment records kept anonymised for accounts | No |

**Rules for all of these**
- Always a reason (from a list + note), who did it and when → shown in an "Activity log".
- Confirm popup showing exactly what will happen (number of students affected, active plans).
- Only the Owner role can Block/Remove a teacher; staff roles can only Pause (with roles in Settings → Team).
- Payment records are never deleted, only kept read-only.
- Teacher can also block a student from his own panel? — owner to decide.

Touches: database (status + reason + log), admin panel (teacher detail + student list), teacher panel (student list), app (blocked / paused screens), backend checks on every request.

---

<!-- Next points from the owner go below as S2, S3, … -->
