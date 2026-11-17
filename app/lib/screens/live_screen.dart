import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../share.dart';
import '../theme.dart';
import 'library_screen.dart';
import 'pay_screen.dart';
import 'test_screen.dart';

/// "Sir, save this" in any language saves the notes of the whole class so far as one PDF.
/// Same lists as the server (backend tutor.py / quiz.py): everything in class can be said on the call.
const _savePhrases = [
  'save this', 'save notes', 'save as notes', 'save it', 'save the notes', 'make notes', 'give me notes',
  'notes provide', 'provide notes', 'notes de do', 'notes dedo', 'notes do', 'notes bana do', 'notes bhej do',
  'notes chahiye', 'notes save', 'notes kar do',
  'सेव कर', 'सेव करो', 'सेव कर दो', 'नोट्स सेव', 'नोट सेव', 'सहेज', 'नोट्स दे दो', 'नोट्स दो', 'नोट्स बना दो',
  'नोट्स भेज दो', 'नोट्स चाहिए', 'नोट्स प्रोवाइड', 'नोट्स प्रोवाइड कर दो',
  'ਸੇਵ ਕਰ', 'ਨੋਟਸ ਸੇਵ', 'ਨੋਟਸ ਦੇ ਦਿਓ', 'ਨੋਟਸ ਬਣਾ ਦਿਓ', 'ਨੋਟਸ ਚਾਹੀਦੇ',
];

/// Lower-case, punctuation → spaces, padded, so phrases match whole words only.
String _padded(String text) =>
    ' ${text.toLowerCase().replaceAll(RegExp(r'[^\w\u0900-\u0A7F]+'), ' ').trim()} ';

bool isSaveCommand(String text) {
  final low = _padded(text);
  return _savePhrases.any((p) => low.contains(' $p '));
}

/// "Sir, test lo" in any language: Sir gives a test on what he taught (same list as the server).
const _testPhrases = [
  'test lo', 'test le lo', 'test lijiye', 'test do', 'take my test', 'give me a test', 'test me', 'quiz me',
  'viva lo', 'viva le lo', 'sawal do', 'sawal pucho', 'test lena', 'test start',
  'टेस्ट लो', 'टेस्ट ले लो', 'टेस्ट लीजिए', 'टेस्ट दो', 'मेरा टेस्ट', 'सवाल दो', 'सवाल पूछो', 'प्रश्न दो',
  'ਟੈਸਟ ਲਓ', 'ਟੈਸਟ ਲੈ ਲਓ', 'ਮੇਰਾ ਟੈਸਟ', 'ਸਵਾਲ ਦਿਓ',
];

bool isTestCommand(String text) {
  // whole words only, so "what does test mean?" is a question, not a command
  final low = _padded(text);
  return _testPhrases.any((p) => low.contains(' $p '));
}

const _modeWords = {
  'mcq': ['mcq', 'objective', 'options', 'एमसीक्यू', 'ऑब्जेक्टिव'],
  'written': ['written', 'likhit', 'likh kar', 'likhkar', 'लिखित', 'लिखकर', 'लिख कर', 'ਲਿਖਤੀ'],
  'oral': ['oral', 'viva', 'bol kar', 'bolkar', 'maukhik', 'मौखिक', 'बोलकर', 'बोल कर', 'वाइवा', 'ਮੌਖਿਕ', 'ਬੋਲ ਕੇ'],
};

/// "Sir, MCQ test lo" / "viva le lo": the kind of test was said on the call — no need to ask.
String? testModeIn(String text) {
  final low = _padded(text);
  for (final e in _modeWords.entries) {
    if (e.value.any((w) => low.contains(' $w '))) return e.key;
  }
  return null;
}

/// Screen 3 · Live class: the teacher's video, what Sir is saying / asking, the save-notes popup,
/// and the call controls (photo, type, speak, end).
class LiveScreen extends StatefulWidget {
  const LiveScreen({super.key});
  @override
  State<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends State<LiveScreen> {
  final _input = TextEditingController();
  final _inputFocus = FocusNode();
  final _started = DateTime.now();
  Timer? _clock;
  Access? _access;
  Answer? _last;
  String? _lastQuestion;
  bool _saved = false; // the class notes are up to date with the answer on screen
  bool _saving = false;
  SavedNote? _note;   // this class's notes PDF
  bool _thinking = false;
  bool _typing = false;

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _refreshAccess());
  }

  @override
  void dispose() {
    _clock?.cancel();
    _input.dispose();
    _inputFocus.dispose();
    super.dispose();
  }

  Future<void> _refreshAccess() async {
    try {
      final a = await AppScope.of(context).api.access();
      if (mounted) setState(() => _access = a);
    } catch (_) {}
  }

  String get _elapsed {
    final d = DateTime.now().difference(_started);
    return '${d.inMinutes.toString().padLeft(2, '0')}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';
  }

  void _toast(String msg) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

  Future<void> _openPlans() async {
    final paid = await Navigator.of(context).push<bool>(
        MaterialPageRoute(builder: (_) => PayScreen(access: _access)));
    if (paid == true) _refreshAccess();
  }

  /// Top-right pill: demo questions left, renew reminder, grace questions, or plan ended.
  Widget? _statusPill(Access? a) {
    if (a == null) return null;
    final accent = AppScope.of(context).cfg.accent;
    const warn = Color(0xFFF59E0B);
    String text;
    Color color;
    switch (a.state) {
      case 'demo':
        text = a.demoLeft == 1 ? 'Demo · 1 question left' : 'Demo · ${a.demoLeft} questions left';
        color = accent;
        break;
      case 'active':
        if (!a.renewSoon) return null;
        text = a.daysLeft == 0 ? 'Plan ends today · Renew' : 'Plan ends in ${a.daysLeft} days · Renew';
        color = warn;
        break;
      case 'grace':
        text = 'Plan ended · ${a.graceLeft} free left · Renew';
        color = warn;
        break;
      default:
        text = 'Plan ended · Renew';
        color = LT.danger;
    }
    return InkWell(
      onTap: _openPlans,
      borderRadius: BorderRadius.circular(999),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: LT.surface,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: color, width: 1.5),
        ),
        child: Text(text, style: TextStyle(color: color == accent ? LT.accentText : color, fontSize: 12, fontWeight: FontWeight.w700)),
      ),
    );
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _thinking) return;
    _input.clear();
    if (isSaveCommand(text)) {
      await _save();
      return;
    }
    if (isTestCommand(text)) {
      await _offerTest(mode: testModeIn(text));
      return;
    }
    setState(() {
      _thinking = true;
      _lastQuestion = text;
    });
    try {
      final a = await AppScope.of(context).api.ask(text);
      setState(() {
        _last = a;
        _saved = false;
        _access = a.access;
      });
    } on CommandException catch (c) {
      if (mounted) setState(() => _thinking = false);
      if (c.command == 'save') {
        await _save();
      } else {
        await _offerTest(mode: testModeIn(text));
      }
    } on ApiException catch (e) {
      if (e.demoOver) {
        _toast(e.message);
        _openPlans();
      } else {
        _toast(e.message);
        if (e.status == 403 || e.status == 503) _refreshAccess(); // AI paused: show the notice on the call screen
      }
    } catch (_) {
      _toast('No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _thinking = false);
    }
  }

  /// Notes of the whole class so far (greetings and small talk left out), one PDF per class.
  Future<void> _save({List<String>? topics}) async {
    if (_saving) return;
    setState(() => _saving = true);
    try {
      final note = await AppScope.of(context).api.saveClassNotes(topics: topics);
      if (mounted) {
        setState(() {
          _note = note;
          _saved = true;
        });
      }
    } on ApiException catch (e) {
      _toast(e.message);
    } catch (_) {
      _toast('Could not save notes. Please try again.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Let the student untick topics before saving.
  Future<void> _chooseTopics() async {
    ClassSummary summary;
    try {
      summary = await AppScope.of(context).api.currentClass();
    } catch (_) {
      _toast('No internet connection. Please try again.');
      return;
    }
    if (!mounted) return;
    if (summary.topics.isEmpty) {
      _toast('Nothing to save yet — ask Sir something about your studies first.');
      return;
    }
    final picked = {for (final t in summary.topics) t.topic};
    final accent = AppScope.of(context).cfg.accent;
    final chosen = await showModalBottomSheet<List<String>>(
      context: context,
      backgroundColor: LT.surface2,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Topics for your notes', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const Text('Untick what you don’t need.', style: TextStyle(color: LT.muted)),
              const SizedBox(height: 8),
              Flexible(
                child: ListView(shrinkWrap: true, children: [
                  for (final t in summary.topics)
                    CheckboxListTile(
                      value: picked.contains(t.topic),
                      activeColor: accent,
                      contentPadding: EdgeInsets.zero,
                      title: Text(t.topic, style: const TextStyle(fontWeight: FontWeight.w600)),
                      onChanged: (v) => setSheet(() => v == true ? picked.add(t.topic) : picked.remove(t.topic)),
                    ),
                ]),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: accent, foregroundColor: LT.onAccent,
                      padding: const EdgeInsets.symmetric(vertical: 14), textStyle: const TextStyle(fontWeight: FontWeight.w800)),
                  onPressed: picked.isEmpty ? null : () => Navigator.of(ctx).pop(picked.toList()),
                  child: Text(picked.length == summary.topics.length ? 'Save all topics' : 'Save ${picked.length} topics'),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
    if (chosen != null) await _save(topics: chosen);
  }

  /// Sir's test on today's topics. Returns true if the student stayed in class (Sir is teaching again).
  Future<bool> _offerTest({String? intro, String? mode}) async {
    mode ??= await chooseTestMode(context, intro: intro);
    if (mode == null || !mounted) return false;
    setState(() => _thinking = true);
    TestState test;
    try {
      test = await AppScope.of(context).api.startTest(mode);
    } on ApiException catch (e) {
      _toast(e.message);
      if (e.demoOver) _openPlans();
      return false;
    } catch (_) {
      _toast('No internet connection. Please try again.');
      return false;
    } finally {
      if (mounted) setState(() => _thinking = false);
    }
    if (!mounted) return false;
    final again = await Navigator.of(context).push<Answer>(MaterialPageRoute(builder: (_) => TestScreen(test: test)));
    _refreshAccess();
    if (again == null || !mounted) return false;
    setState(() {
      _last = again;
      _lastQuestion = 'Please teach me again';
      _saved = false;
      _access = again.access;
    });
    return true;
  }

  Future<void> _endClass(Access? access) async {
    final end = await confirmAction(context, title: 'End this class?',
        message: 'You can start again any time. Your saved notes stay in your library.', confirmLabel: 'End class', danger: true);
    if (!end || !mounted) return;
    ClassSummary? summary;
    try {
      summary = await AppScope.of(context).api.endClass();
    } catch (_) {}
    if (!mounted) return;
    if (summary != null && summary.canTest) {
      final take = await confirmAction(context, title: 'Quick test before you go?',
          message: 'Sir has a few questions on today’s topics. It takes about 5 minutes.', confirmLabel: 'Take the test');
      if (!mounted) return;
      if (take && await _offerTest()) return; // Sir is teaching again: stay in class
      if (!mounted) return;
    }
    (access != null && access.state != 'active') ? _openPlans() : _openLibrary();
  }

  void _openLibrary() => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const LibraryScreen()));

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final cfg = scope.cfg;
    final access = _access;
    return PopScope(
      canPop: false,   // phone back button: ask before leaving the class
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final leave = await confirmAction(context, title: 'Leave the class?',
            message: 'Your saved notes stay in your library. You can come back any time.', confirmLabel: 'Leave', danger: true);
        if (leave) SystemNavigator.pop();
      },
      child: Scaffold(
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        child: Column(
          children: [
            // ---- top bar ----
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
              child: Row(children: [
                RoundIconButton(icon: Icons.menu_book_rounded, tooltip: 'My library', size: 44,
                    background: LT.surface, onPressed: _openLibrary),
                const SizedBox(width: 10),
                Expanded(
                  child: GestureDetector(
                    onLongPress: scope.api is DemoApi
                        ? () {
                            final a = (scope.api as DemoApi).simulateNext();
                            setState(() => _access = a);
                            _toast('Demo preview: plan state → ${a.state}${a.renewSoon ? ' (renew soon)' : ''}');
                          }
                        : null,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(cfg.teacherName, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                      Text('${cfg.subject} · $_elapsed', style: const TextStyle(fontSize: 12, color: LT.muted)),
                    ]),
                  ),
                ),
                if (_statusPill(access) != null) _statusPill(access)!,
                const SizedBox(width: 6),
                RoundIconButton(icon: Icons.quiz_outlined, tooltip: 'Take a test', size: 40,
                    background: LT.surface, onPressed: () => _offerTest()),
                const SizedBox(width: 6),
                RoundIconButton(icon: Icons.share_outlined, tooltip: 'Share this app', size: 40,
                    background: LT.surface, onPressed: () => shareApp(context)),
              ]),
            ),
            // ---- safety notice from the server (warning / AI paused) ----
            if (access?.notice != null) _safetyNotice(access!),
            // ---- teacher video (Phase 2: live avatar video replaces the photo) ----
            Expanded(
              flex: 5,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(28),
                  child: Stack(fit: StackFit.expand, children: [
                    Image.asset(cfg.avatar, fit: BoxFit.cover, alignment: const Alignment(0, -0.7)),
                    if (_thinking)
                      const Align(
                        alignment: Alignment.bottomCenter,
                        child: Padding(padding: EdgeInsets.all(14), child: _ThinkingDots()),
                      ),
                  ]),
                ),
              ),
            ),
            // ---- what Sir is saying ----
            Expanded(
              flex: 4,
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(18, 14, 18, 6),
                child: _last == null ? _welcome(cfg.teacherName) : _answerView(_last!),
              ),
            ),
            if (_typing) _textInput(cfg.accent),
            // ---- call controls ----
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 18),
              child: Row(mainAxisAlignment: MainAxisAlignment.spaceAround, children: [
                RoundIconButton(icon: Icons.photo_camera_outlined, tooltip: 'Ask with a photo',
                    onPressed: () => _toast('Photo questions are coming in the next update')),
                RoundIconButton(icon: Icons.keyboard_alt_outlined, tooltip: 'Type a question',
                    background: _typing ? LT.accentSoft : null,
                    onPressed: () {
                      setState(() => _typing = !_typing);
                      if (_typing) _inputFocus.requestFocus();
                    }),
                RoundIconButton(icon: Icons.mic_rounded, tooltip: 'Hold to speak', size: 76,
                    background: cfg.accent, foreground: LT.onAccent,
                    onPressed: () => _toast('Voice is coming in the next update — tap the keyboard to type for now')),
                RoundIconButton(icon: Icons.call_end_rounded, tooltip: 'End class', background: LT.danger,
                    onPressed: () => _endClass(access)),
              ]),
            ),
          ],
        ),
      ),
    ));
  }

  Widget _safetyNotice(Access a) {
    final paused = a.aiPaused || a.accountMessage == null; // a platform pause also stops Sir
    final color = paused ? LT.danger : const Color(0xFFF59E0B);
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withAlpha(36),
        border: Border.all(color: color.withAlpha(150)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(paused ? Icons.block_rounded : Icons.warning_amber_rounded, color: color, size: 20),
        const SizedBox(width: 10),
        Expanded(child: Text(a.notice!, style: const TextStyle(fontSize: 13, height: 1.35))),
      ]),
    );
  }

  Widget _welcome(String teacher) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('SIR IS LISTENING', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
        const SizedBox(height: 8),
        Text('Namaste! Ask $teacher anything — in Hindi, English, Punjabi or any language.',
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, height: 1.4)),
      ]);

  Widget _answerView(Answer a) {
    final accent = AppScope.of(context).cfg.accent;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (_lastQuestion != null)
        Text('You: $_lastQuestion', style: const TextStyle(fontSize: 13, color: LT.muted)),
      const SizedBox(height: 6),
      Text(a.answer, style: const TextStyle(fontSize: 16, height: 1.45)),
      const SizedBox(height: 8),
      if (a.origin != 'redirect') Row(children: [
        Icon(a.origin == 'general_ai' ? Icons.info_outline : Icons.check, size: 15, color: LT.accentText),
        const SizedBox(width: 6),
        Expanded(
          child: Text('Source: ${a.sources.join(' · ')}',
              style: const TextStyle(fontSize: 12, color: LT.accentText, fontWeight: FontWeight.w600)),
        ),
      ]),
      if (a.followUp.isNotEmpty) ...[
        const SizedBox(height: 14),
        const Text('SIR IS ASKING', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
        const SizedBox(height: 6),
        Text(a.followUp, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, height: 1.4)),
      ],
      if (a.verifyCode.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('Ref ${a.verifyCode}', style: const TextStyle(fontSize: 11, color: LT.muted, letterSpacing: 0.5)),
      ],
      const SizedBox(height: 12),
      if (a.origin != 'redirect') _saved ? _savedBanner(accent) : _savePopup(accent),
    ]);
  }

  Widget _savePopup(Color accent) => Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        decoration: BoxDecoration(
          color: LT.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: accent, width: 1.5),
        ),
        child: Row(children: [
          Container(
            width: 36, height: 36,
            decoration: BoxDecoration(color: LT.accentSoft, borderRadius: BorderRadius.circular(10)),
            child: const Icon(Icons.description_outlined, color: LT.accentText, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(_note == null ? 'Save today’s class as notes?' : 'Update your class notes?',
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
              const Text('Topic-wise PDF · or say “Sir, save this”', style: TextStyle(fontSize: 11, color: LT.muted)),
              GestureDetector(
                onTap: _saving ? null : _chooseTopics,
                child: const Padding(
                  padding: EdgeInsets.only(top: 2),
                  child: Text('Choose topics', style: TextStyle(fontSize: 12, color: LT.accentText,
                      fontWeight: FontWeight.w700, decoration: TextDecoration.underline)),
                ),
              ),
            ]),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: accent, foregroundColor: LT.onAccent,
                textStyle: const TextStyle(fontWeight: FontWeight.w800)),
            onPressed: _saving ? null : () => _save(),
            child: Text(_saving ? 'Saving…' : 'Save'),
          ),
        ]),
      );

  Widget _savedBanner(Color accent) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: LT.accentSoft,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: accent, width: 1.5),
        ),
        child: Row(children: [
          CircleAvatar(radius: 14, backgroundColor: accent, child: const Icon(Icons.check, size: 16, color: LT.onAccent)),
          const SizedBox(width: 12),
          const Expanded(child: Text('Class notes saved in your Library', style: TextStyle(fontWeight: FontWeight.w700))),
          if (_note != null)
            IconButton(tooltip: 'Share notes', icon: const Icon(Icons.share_outlined, size: 20),
                onPressed: () => shareNote(context, _note!)),
          TextButton(onPressed: _openLibrary, child: const Text('Open')),
        ]),
      );

  Widget _textInput(Color accent) => Padding(
        padding: const EdgeInsets.fromLTRB(14, 4, 14, 0),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _input,
              focusNode: _inputFocus,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: const InputDecoration(hintText: 'Ask Sir anything…', isDense: true),
            ),
          ),
          const SizedBox(width: 8),
          RoundIconButton(icon: Icons.send_rounded, tooltip: 'Send', size: 48, background: accent,
              foreground: LT.onAccent, onPressed: _send),
        ]),
      );
}

class _ThinkingDots extends StatelessWidget {
  const _ThinkingDots();
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(color: LT.bg, borderRadius: BorderRadius.circular(999)),
        child: const Row(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: LT.accentText)),
          SizedBox(width: 8),
          Text('Sir is thinking…', style: TextStyle(fontSize: 12, color: LT.text)),
        ]),
      );
}
