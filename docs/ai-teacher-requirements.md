# AI Teacher – Real Human-Like Teaching Experience (requirements from Durina, 17 Nov 2026)

**Goal:** the student should feel a real human teacher is personally teaching them — not a robot or a
plain AI video. Vision: *Call your AI teacher, anytime.*

Instructions from Durina: integrate with the Teaching Style system; give a setting/toggle per feature
where useful; keep the UI modern and clean; build phase-wise by feasibility, quality and performance.

## How each requirement is delivered

| # | Requirement | Where it lives | Phase |
|---|---|---|---|
| 6 | Intelligent teaching: adapt to student level, use student's name, instant doubt solving, engagement, adjust speed and explanation, personalised approach | Tutor engine (`style.py`, `tutor.py`): student level tracked per student, name in prompt, recent conversation as context, simpler/deeper explanations by level | **Now** |
| 7 | Interaction: ask questions while teaching, wait for the answer, praise correct, politely correct wrong, motivate, react naturally | Follow-up question after every answer; the student's reply is checked against it → praise / gentle correction; level goes up or down | **Now** |
| 8 | Smart explanations: real-life examples, stories, step-by-step, visual / board, memory tricks, exam points | Teaching Style toggles → prompt rules; every answer also returns `board` points (what goes on the board) | **Now** (text + board points); drawn diagrams in Phase 5 |
| 11 | Human conversation: natural expressions, pauses, context-aware, self-correction, friendly, never robotic or repetitive | Prompt rules + last answers sent as context with "don't repeat" rule | **Now** |
| 12 | Personality: Friendly, Strict, Motivational, Professional, Funny & Interactive, Calm & Patient | Teacher picks one main personality (+ optional second) in Teaching Style | **Now** |
| 4 | Voice: natural, emotion-based modulation, pauses, pronunciation, emphasis, Hindi+English, tones per situation | Engine already returns `emotion` and `emphasis` words for every answer; voice clone + speech in teacher's voice uses them | Text-side **now**, voice **Phase 5** |
| 1 | Facial expressions: smile, happy/sad, serious/thinking, surprise, encouraging | Avatar driven by the `emotion` tag of each answer | **Phase 5** |
| 2 | Body language: gestures, head movement, posture, hands while explaining | Avatar engine (video model) | **Phase 5** |
| 3 | Eye contact: camera eye contact, blinking, looking at the board, natural eye movement | Avatar engine; "looking at board" when `board` points are shown | **Phase 5** |
| 5 | Lip sync: accurate, realistic mouth, voice + expression in sync | Avatar engine with the teacher's cloned voice | **Phase 5** |
| 9 | Continuity: same face, voice, clothes, background, smooth transitions | One fixed avatar profile per teacher (photo/video + voice + background), set once in the admin panel | **Phase 5** |
| 10 | Smart board: pointing, diagrams, writing/drawing, highlighting | Board panel in the live class built from `board` points; avatar points at it | Board text **Phase 2 app update**, pointing/drawing **Phase 5** |
| 13 | Overall: real-time, emotion-aware, personalised, consistent personality, seamless voice+video+AI | All of the above | Ongoing |

## Rules for writing code from now on
1. Every tutor answer returns: `answer`, `follow_up`, `emotion` (smile / encouraging / thinking / serious /
   excited / calm), `emphasis` (important words), `board` (2–5 short points), `language`.
   Phase 5 voice and avatar consume these fields — never remove them.
2. Teaching behaviour is configured per teacher in **Teaching Style**, not hard-coded.
3. The engine keeps a per-student `level` (beginner / intermediate / advanced) and adapts explanations.
4. Never robotic: no fixed greeting lines, vary wording, use the student's name sometimes, not always.
5. The same teacher must always look, sound and behave the same (continuity).
