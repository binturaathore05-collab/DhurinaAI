import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Audio mode (owner, 17 Nov 2026): the student speaks, Sir speaks back.
///
/// Uses the phone's own free speech recognition and text-to-speech (no AI cost). The text goes to the server exactly
/// like a typed question, so the same safety check, commands ("Sir notes de do", "Maths wale sir ko bulao") and
/// teacher switching apply. Each teacher gets their own voice (a different phone voice / pitch), so a switch is heard.
class Voice {
  Voice._();
  static final Voice instance = Voice._();

  final SpeechToText _stt = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  bool _sttReady = false;
  bool _ttsReady = false;
  int _gen = 0; // bumps on every stop: a running sentence loop ends
  List<dynamic> _voices = const [];
  void Function(String status)? _onStatus;
  void Function(String error)? _onError;

  bool get listening => _stt.isListening;

  // ---------- listening ----------

  /// Starts listening. [onWords] gets the words so far; [onDone] the final words when the student stops speaking
  /// (about 2.5 s of silence) or presses the mic again. Returns false if the phone can't listen (no permission).
  Future<bool> listen({
    required String language,
    required void Function(String words) onWords,
    required void Function(String words) onDone,
    void Function(String error)? onError,
  }) async {
    await stopSpeaking();
    _onError = onError;
    if (!_sttReady) {
      _sttReady = await _stt.initialize(
        onError: (SpeechRecognitionError e) => _onError?.call(e.errorMsg),
        onStatus: (s) => _onStatus?.call(s),
      );
      if (!_sttReady) return false;
    }
    var finished = false;
    var last = '';
    void finish() {
      if (finished) return;
      finished = true;
      onDone(last.trim());
    }

    _onStatus = (s) {
      if (s == 'done' || s == 'notListening') finish();
    };
    final locale = await _sttLocale(language);
    await _stt.listen(
      listenOptions: SpeechListenOptions(
        localeId: locale,
        listenFor: const Duration(seconds: 60),
        pauseFor: const Duration(milliseconds: 2500),
        partialResults: true,
        listenMode: ListenMode.dictation,
        cancelOnError: true,
      ),
      onResult: (SpeechRecognitionResult r) {
        last = r.recognizedWords;
        onWords(last);
        if (r.finalResult) finish();
      },
    );
    return true;
  }

  /// The mic was pressed again: stop and send what was heard.
  Future<void> stopListening() => _stt.stop();

  /// Leaving the screen: stop without sending.
  Future<void> cancelListening() async {
    _onStatus = null;
    await _stt.cancel();
  }

  Future<String> _sttLocale(String language) async {
    final want = language == 'en' ? 'en_IN' : language.startsWith('pa') ? 'pa_IN' : 'hi_IN';
    try {
      final have = (await _stt.locales()).map((l) => l.localeId.replaceAll('-', '_')).toSet();
      if (have.contains(want)) return want;
      if (have.contains('hi_IN')) return 'hi_IN';
      if (have.contains('en_IN')) return 'en_IN';
    } catch (_) {}
    return want;
  }

  // ---------- speaking ----------

  Future<void> _initTts() async {
    if (_ttsReady) return;
    await _tts.awaitSpeakCompletion(true);
    try {
      _voices = (await _tts.getVoices as List?) ?? const [];
    } catch (_) {
      _voices = const [];
    }
    _ttsReady = true;
  }

  /// Phone language for the answer: Hinglish in Roman letters reads better with an Indian-English voice.
  static String ttsLanguage(String answerLanguage) {
    final code = answerLanguage.toLowerCase();
    if (code == 'hi-latn' || code.startsWith('en')) return 'en-IN';
    final base = code.split('-').first;
    return '$base-IN';
  }

  Future<void> _setVoice(String language, int teacherKey, String emotion) async {
    var lang = language;
    if (await _tts.isLanguageAvailable(lang) != true) lang = lang.startsWith('en') ? 'en-IN' : 'hi-IN';
    await _tts.setLanguage(lang);
    // each teacher: another installed voice of that language if the phone has one, and a slightly different pitch
    final same = _voices
        .whereType<Map>()
        .where((v) => (v['locale'] ?? '').toString().replaceAll('_', '-').toLowerCase() == lang.toLowerCase())
        .toList();
    if (same.isNotEmpty) {
      final v = same[teacherKey.abs() % same.length];
      await _tts.setVoice({'name': v['name'].toString(), 'locale': v['locale'].toString()});
    }
    const pitches = [1.0, 0.88, 1.12, 0.94, 1.06];
    var pitch = pitches[teacherKey.abs() % pitches.length];
    var rate = 0.48;
    if (emotion == 'happy' || emotion == 'encouraging' || emotion == 'excited') pitch += 0.04;
    if (emotion == 'serious' || emotion == 'thinking') rate = 0.44;
    await _tts.setPitch(pitch);
    await _tts.setSpeechRate(rate);
  }

  /// Splits Sir's text into sentences, so the one being spoken can be shown and Stop works between sentences.
  static List<String> sentences(String text) => text
      .split(RegExp(r'(?<=[।॥!?])\s+|(?<=\.)\s+(?=\D)|\n+'))
      .map((s) => s.trim())
      .where((s) => s.isNotEmpty)
      .toList();

  /// Speaks [parts] one after the other. [onSentence] gets the index of the part being spoken (-1 at the end).
  /// Returns false if it was stopped.
  Future<bool> speak(List<String> parts,
      {required String language, int teacherKey = 0, String emotion = 'smile', void Function(int i)? onSentence}) async {
    await _initTts();
    final gen = ++_gen;
    try {
      await _setVoice(ttsLanguage(language), teacherKey, emotion);
      for (var i = 0; i < parts.length; i++) {
        if (gen != _gen) return false;
        onSentence?.call(i);
        await _tts.speak(parts[i]);
      }
    } catch (_) {
      // a phone without speech: the text is still on screen
    } finally {
      if (gen == _gen) onSentence?.call(-1);
    }
    return gen == _gen;
  }

  Future<void> stopSpeaking() async {
    _gen++;
    try {
      await _tts.stop();
    } catch (_) {}
  }
}
