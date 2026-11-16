# Product decisions (from planning with Durina Ventures)

- **Brand:** LiveTeach. Each teacher gets a white-label app published on the teacher's own Play Console.
- **Final UI:** "Video Call" design, 6 screens: Login → OTP → Live Class → My Library → Pay Now → Payment Successful.
- **Languages:** app screens stay in English, with no language picker. The teacher automatically answers in
  the language the student speaks or types (Hindi, English, Punjabi, Hinglish, any Indian language).
- **Saving notes:** never a separate screen. During the live call a popup offers "Save", or the student says
  "Sir, save this" (any language). The answer becomes a PDF in My Library.
- **My Library:** saved notes box + full question history.
- **Payment:** single "Pay Now" button → Razorpay. Teacher's merchant account; Durina's commission (20%)
  split automatically with Razorpay Route.
- **Answer accuracy:** verified answers → teacher's notes → general AI (flagged for teacher review).
- **Tech:** Flutter app, Python FastAPI backend, phases: Phase 1 = chat + teacher voice; Phase 2 = video avatar.
