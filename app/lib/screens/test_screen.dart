import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../share.dart';
import '../theme.dart';
import '../voice.dart';

/// Ask the student how they want Sir's test: MCQ, written or oral. Returns the mode, or null.
Future<String?> chooseTestMode(BuildContext context, {String? intro}) => showModalBottomSheet<String>(
      context: context,
      backgroundColor: LT.surface2,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Test on today’s topics', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(intro ?? 'How would you like Sir to test you?', style: const TextStyle(color: LT.muted, height: 1.4)),
            const SizedBox(height: 14),
            _modeTile(ctx, 'mcq', Icons.checklist_rounded, 'MCQ', 'Tap one of 4 options · checked instantly'),
            _modeTile(ctx, 'written', Icons.edit_note_rounded, 'Written', 'Short answers · Sir checks the key points'),
            _modeTile(ctx, 'oral', Icons.record_voice_over_outlined, 'Oral (viva)', 'Sir asks one by one · answer in a line or two'),
          ]),
        ),
      ),
    );

Widget _modeTile(BuildContext ctx, String mode, IconData icon, String title, String sub) => ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4),
      leading: CircleAvatar(backgroundColor: LT.accentSoft, child: Icon(icon, color: LT.accentText)),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
      subtitle: Text(sub, style: const TextStyle(color: LT.muted, fontSize: 12)),
      onTap: () => Navigator.of(ctx).pop(mode),
    );

/// Sir's test, one question at a time. Pops with Sir's new explanation (an [Answer]) when the student
/// says "yes, teach me again", otherwise with null.
class TestScreen extends StatefulWidget {
  final TestState test;
  const TestScreen({super.key, required this.test});
  @override
  State<TestScreen> createState() => _TestScreenState();
}

class _TestScreenState extends State<TestScreen> {
  late TestState _test = widget.test;
  final _input = TextEditingController();
  AnswerCheck? _check; // feedback on the question just answered
  int? _picked;
  bool _busy = false;
  bool _listening = false;
  int _askedIndex = -1; // oral test: the question Sir has read out

  @override
  void dispose() {
    Voice.instance.stopSpeaking();
    Voice.instance.cancelListening();
    _input.dispose();
    super.dispose();
  }

  /// Oral (viva): Sir reads each question aloud once.
  void _readQuestion(TestState t) {
    if (t.mode != 'oral' || t.question == null || _askedIndex == t.index) return;
    _askedIndex = t.index;
    final lang = RegExp(r'[\u0900-\u097F]').hasMatch(t.question!.q) ? 'hi' : 'en';
    WidgetsBinding.instance.addPostFrameCallback((_) => Voice.instance.speak([t.question!.q], language: lang));
  }

  /// Oral (viva): answer by speaking; the words go into the box (the student can still fix them) and are sent.
  Future<void> _speakAnswer() async {
    if (_listening) return Voice.instance.stopListening();
    setState(() => _listening = true);
    final ok = await Voice.instance.listen(
      language: RegExp(r'[\u0900-\u097F]').hasMatch(_test.question?.q ?? '') ? 'hi' : 'en',
      onWords: (w) {
        if (mounted) setState(() => _input.text = w);
      },
      onDone: (w) {
        if (!mounted) return;
        setState(() => _listening = false);
        if (w.trim().isNotEmpty) _submit(w.trim());
      },
      onError: (_) {
        if (mounted) setState(() => _listening = false);
      },
    );
    if (!ok && mounted) {
      setState(() => _listening = false);
      _toast('Please allow the microphone for this app, or type your answer.');
    }
  }

  void _toast(String msg) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

  Future<void> _submit(Object answer) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final c = await AppScope.of(context).api.answerTest(_test.id, answer);
      if (mounted) setState(() => _check = c);
    } on ApiException catch (e) {
      _toast(e.message);
    } catch (_) {
      _toast('No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _next() => setState(() {
        _test = _check!.test;
        _check = null;
        _picked = null;
        _input.clear();
      });

  Future<void> _reteach(bool yes) async {
    setState(() => _busy = true);
    try {
      final a = await AppScope.of(context).api.reteach(_test.id, yes);
      if (mounted) Navigator.of(context).pop(a);
    } on ApiException catch (e) {
      _toast(e.message);
    } catch (_) {
      _toast('No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirmLeave() async {
    if (_test.done) return true;
    return confirmAction(context,
        title: 'Leave the test?', message: 'Your answers so far are kept, but this test will stay unfinished.',
        confirmLabel: 'Leave', danger: true);
  }

  @override
  Widget build(BuildContext context) {
    final accent = AppScope.of(context).cfg.accent;
    final t = _test;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (await _confirmLeave() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: LT.bg,
          title: Text('${testModes[t.mode] ?? 'Test'} test', style: const TextStyle(fontWeight: FontWeight.w800)),
        ),
        body: SafeArea(
          child: ListView(padding: const EdgeInsets.fromLTRB(18, 6, 18, 24), children: [
            if (!(t.done && _check == null)) ...[
              LinearProgressIndicator(
                value: (t.index + (_check != null ? 1 : 0)) / t.total,
                color: accent, backgroundColor: LT.surface, minHeight: 6, borderRadius: BorderRadius.circular(99)),
              const SizedBox(height: 8),
              Text('Question ${t.index + 1} of ${t.total}', style: const TextStyle(color: LT.muted, fontSize: 12)),
              const SizedBox(height: 14),
            ],
            if (_check != null) _feedback(_check!, accent)
            else if (t.done && t.result != null) _result(t.result!, accent)
            else if (t.question != null) _questionView(t, accent),
          ]),
        ),
      ),
    );
  }

  Widget _questionView(TestState t, Color accent) {
    final q = t.question!;
    _readQuestion(t);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (t.mode == 'oral')
        const Text('SIR IS ASKING', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
      Text(q.q, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700, height: 1.4)),
      const SizedBox(height: 18),
      if (t.mode == 'mcq') ...[
        for (var i = 0; i < q.options.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: _busy ? null : () => setState(() => _picked = i),
              child: Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: _picked == i ? LT.accentSoft : LT.surface,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: _picked == i ? accent : LT.border, width: 1.5),
                ),
                child: Row(children: [
                  CircleAvatar(radius: 14, backgroundColor: _picked == i ? accent : LT.surface2,
                      child: Text('ABCD'[i], style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13,
                          color: _picked == i ? LT.onAccent : LT.text))),
                  const SizedBox(width: 12),
                  Expanded(child: Text(q.options[i], style: const TextStyle(fontSize: 16, height: 1.35))),
                ]),
              ),
            ),
          ),
        const SizedBox(height: 6),
        _primary(accent, _busy ? 'Checking…' : 'Submit', _picked == null || _busy ? null : () => _submit(_picked!)),
      ] else ...[
        TextField(
          controller: _input,
          minLines: t.mode == 'oral' ? 2 : 4,
          maxLines: 8,
          decoration: InputDecoration(
              hintText: t.mode == 'oral' ? 'Answer Sir in a line or two…' : 'Write your answer…'),
        ),
        if (t.mode == 'oral') ...[
          const SizedBox(height: 12),
          Center(
            child: FilledButton.icon(
              onPressed: _busy ? null : _speakAnswer,
              style: FilledButton.styleFrom(backgroundColor: accent, foregroundColor: LT.onAccent,
                  minimumSize: const Size(220, 56), shape: const StadiumBorder()),
              icon: Icon(_listening ? Icons.stop_rounded : Icons.mic_rounded),
              label: Text(_listening ? 'Listening… tap to send' : 'Speak your answer',
                  style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ),
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Center(child: Text('Or type it in the box above.', style: TextStyle(color: LT.muted, fontSize: 12))),
          ),
        ],
        const SizedBox(height: 14),
        Row(children: [
          TextButton(onPressed: _busy ? null : () => _submit(''), child: const Text('Skip')),
          const Spacer(),
          _primary(accent, _busy ? 'Sir is checking…' : 'Submit', _busy ? null : () {
            if (_input.text.trim().isEmpty) {
              _toast('Write your answer, or tap Skip.');
              return;
            }
            _submit(_input.text.trim());
          }),
        ]),
      ],
    ]);
  }

  Widget _feedback(AnswerCheck c, Color accent) {
    final partly = !c.correct && c.score > 0;
    final color = c.correct ? accent : partly ? const Color(0xFFF59E0B) : LT.danger;
    final q = _test.question;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (q != null) Text(q.q, style: const TextStyle(fontSize: 15, color: LT.muted, height: 1.4)),
      const SizedBox(height: 12),
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: LT.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: color, width: 1.5)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(c.correct ? Icons.check_circle : partly ? Icons.adjust_rounded : Icons.cancel, color: color),
            const SizedBox(width: 8),
            Text(c.correct ? 'Correct!' : partly ? 'Partly right' : 'Not correct',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: color)),
          ]),
          if (c.feedback.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(c.feedback, style: const TextStyle(fontSize: 15, height: 1.4)),
          ],
          if (!c.correct && c.correctAnswer.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text('RIGHT ANSWER', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
            const SizedBox(height: 4),
            Text(c.correctAnswer, style: const TextStyle(fontSize: 15, height: 1.4, fontWeight: FontWeight.w600)),
          ],
        ]),
      ),
      const SizedBox(height: 16),
      Align(
        alignment: Alignment.centerRight,
        child: _primary(accent, c.test.done ? 'See result' : 'Next question', _next),
      ),
    ]);
  }

  Widget _result(TestResult r, Color accent) {
    final cfg = AppScope.of(context).cfg;
    final icon = r.outcome == 'praise' ? Icons.emoji_events_rounded : r.outcome == 'good' ? Icons.thumb_up_alt_rounded : Icons.school_rounded;
    return Column(crossAxisAlignment: CrossAxisAlignment.center, children: [
      const SizedBox(height: 8),
      CircleAvatar(radius: 40, backgroundColor: LT.accentSoft, child: Icon(icon, size: 42, color: accent)),
      const SizedBox(height: 14),
      Text(r.scoreText, style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w900)),
      Text('${r.percent}%', style: const TextStyle(color: LT.muted, fontWeight: FontWeight.w700)),
      const SizedBox(height: 16),
      Text('${widget.test.teacherName ?? cfg.teacherName} says', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
      const SizedBox(height: 6),
      Text(r.message, textAlign: TextAlign.center, style: const TextStyle(fontSize: 17, height: 1.45, fontWeight: FontWeight.w600)),
      const SizedBox(height: 22),
      if (r.outcome == 'reteach_offer') ...[
        SizedBox(
          width: double.infinity,
          child: _primary(accent, _busy ? 'Please wait…' : 'Yes, teach me again', _busy ? null : () => _reteach(true)),
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(onPressed: _busy ? null : () => _reteach(false), child: const Text('No, not now')),
        ),
      ] else
        SizedBox(
          width: double.infinity,
          child: _primary(accent, 'Back to class', () => Navigator.of(context).pop()),
        ),
      const SizedBox(height: 8),
      TextButton.icon(
        onPressed: () => shareTestResult(context, r),
        icon: const Icon(Icons.share_outlined),
        label: const Text('Share my score'),
      ),
    ]);
  }

  Widget _primary(Color accent, String label, VoidCallback? onPressed) => FilledButton(
        style: FilledButton.styleFrom(
            backgroundColor: accent, foregroundColor: LT.onAccent, padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
            textStyle: const TextStyle(fontWeight: FontWeight.w800)),
        onPressed: onPressed,
        child: Text(label),
      );
}
