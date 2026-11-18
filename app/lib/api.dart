import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';

class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);
  bool get demoOver => status == 402;
  @override
  String toString() => message;
}

/// The server recognised a class command ("Sir, save this" / "Sir, test lo") instead of a question.
class CommandException implements Exception {
  final String command; // save | test | delete
  CommandException(this.command);
}

class Plan {
  final String id;
  final String name;
  final int amountPaise;
  final int durationDays;
  Plan(this.id, this.name, this.amountPaise, this.durationDays);
  factory Plan.fromJson(Map<String, dynamic> j) =>
      Plan(j['id'] as String, j['name'] as String, (j['amount_paise'] as num).toInt(), (j['duration_days'] as num).toInt());
  String get price => amountPaise > 0 ? '₹${(amountPaise / 100).toStringAsFixed(0)}' : '₹—';
}

/// Where the student stands: demo → active (renew reminder near the end) → grace → expired.
class Access {
  final String state; // demo | active | grace | expired
  final int demoLeft;
  final int? daysLeft;
  final bool renewSoon;
  final DateTime? planEndedAt;
  final int graceLeft;
  /// Safety status from the server (A3): active | warning | suspended | review | disabled, with a ready message.
  final String accountStatus;
  final String? accountMessage;
  /// Set when the AI is switched off in admin → Emergency (for everyone or this teacher).
  final String? serviceMessage;
  /// B1: the class isn't known yet / a parent's OK is still needed (under 18).
  final bool profileNeeded;
  final bool consentNeeded;
  final List<ClassOption> classOptions;
  /// Multi-teacher: the teacher the student is with now (shown when the class screen opens).
  final Faculty? activeFaculty;
  Access(this.state, this.demoLeft,
      {this.daysLeft, this.renewSoon = false, this.planEndedAt, this.graceLeft = 0,
      this.accountStatus = 'active', this.accountMessage, this.serviceMessage,
      this.profileNeeded = false, this.consentNeeded = false, this.classOptions = const [], this.activeFaculty});

  /// Still something to do before the class can start.
  bool get setupNeeded => profileNeeded || consentNeeded;

  Access withSetup({required bool profileNeeded, required bool consentNeeded}) => Access(state, demoLeft,
      daysLeft: daysLeft, renewSoon: renewSoon, planEndedAt: planEndedAt, graceLeft: graceLeft,
      accountStatus: accountStatus, accountMessage: accountMessage, serviceMessage: serviceMessage,
      profileNeeded: profileNeeded, consentNeeded: consentNeeded, classOptions: ClassOption.defaults,
      activeFaculty: activeFaculty);

  /// What the call screen shows above Sir (account first, then a platform pause).
  String? get notice => accountMessage ?? serviceMessage;

  /// Sir's AI is paused for this student (notes and library still work).
  bool get aiPaused => accountStatus == 'suspended' || accountStatus == 'review' || accountStatus == 'disabled';

  bool get subscribed => state == 'active';
  bool get hadPlan => state == 'grace' || state == 'expired' || state == 'active';

  factory Access.fromJson(Map<String, dynamic> j) {
    final ended = j['plan_ended_at'] as num?;
    return Access(
      j['state'] as String? ?? (j['subscribed'] == true ? 'active' : 'demo'),
      (j['demo_questions_left'] as num? ?? 0).toInt(),
      daysLeft: (j['days_left'] as num?)?.toInt(),
      renewSoon: j['renew_soon'] == true,
      planEndedAt: ended == null ? null : DateTime.fromMillisecondsSinceEpoch((ended * 1000).toInt()),
      graceLeft: (j['grace_questions_left'] as num? ?? 0).toInt(),
      accountStatus: j['account_status'] as String? ?? 'active',
      accountMessage: j['account_message'] as String?,
      serviceMessage: j['service_message'] as String?,
      profileNeeded: j['profile_needed'] == true,
      consentNeeded: j['consent_needed'] == true,
      classOptions: ((j['class_options'] as List?) ?? [])
          .map((o) => ClassOption((o as Map)['value'].toString(), o['label'].toString()))
          .toList(),
      activeFaculty: Faculty.fromJson(j['active_faculty']),
    );
  }
}

/// One choice on the "Which class are you in?" screen.
class ClassOption {
  final String value; // "6".."12" or "college"
  final String label;
  const ClassOption(this.value, this.label);
  static const defaults = [
    ClassOption('6', 'Class 6'), ClassOption('7', 'Class 7'), ClassOption('8', 'Class 8'), ClassOption('9', 'Class 9'),
    ClassOption('10', 'Class 10'), ClassOption('11', 'Class 11'), ClassOption('12', 'Class 12'),
    ClassOption('college', 'College / exam preparation'),
  ];
}

/// One AI teacher of the institute (multi-teacher). The server says who is answering; the app shows that
/// teacher's face and name and, on a switch, a short "call transfer" line first.
class Faculty {
  final int id;
  final String name;
  final String? avatarUrl; // server path such as /faculty/3/avatar (null = no photo uploaded)
  final String? voiceId;
  final List<String> subjects;
  const Faculty(this.id, this.name, {this.avatarUrl, this.voiceId, this.subjects = const []});
  static Faculty? fromJson(Object? j) {
    if (j is! Map) return null;
    final id = j['id'], name = j['name'];
    if (id is! num || name is! String) return null;
    return Faculty(id.toInt(), name,
        avatarUrl: j['avatar_url'] as String?, voiceId: j['voice_id'] as String?,
        subjects: ((j['subjects'] as List?) ?? []).map((s) => s.toString()).toList());
  }
}

/// The student's own account (Profile screen).
class Me {
  final String name;
  final String phone;
  final String? classLevel;
  final String consent; // not_needed | needed | given | withdrawn
  final bool freePlan;  // a plan given by the institute / Dhurina without payment
  final Access access;
  const Me(this.name, this.phone, this.classLevel, this.consent, this.freePlan, this.access);
  factory Me.fromJson(Map<String, dynamic> j) => Me(
        j['name'] as String? ?? '',
        j['phone'] as String? ?? '',
        j['class_level'] as String?,
        j['consent'] as String? ?? 'needed',
        (j['plan'] as Map?)?['free_until'] != null,
        Access.fromJson(j),
      );
}

class Answer {
  final int qaId;
  final String answer;
  final String followUp;
  final String origin; // verified | teacher_notes | general_ai | redirect (off-topic / blocked)
  final List<String> sources;
  final String language;
  final Access access;
  /// Reference code of this answer (e.g. LT-7F3K-92QD): lets Dhurina prove what Sir really said.
  final String verifyCode;
  /// Multi-teacher: who answered, whether the student was just moved to this teacher, and the fixed line
  /// the old teacher says before the new face appears ("…main aapko Gupta Sir se jod raha hoon").
  final Faculty? faculty;
  final bool switched;
  final String handover;
  /// Sir's mood for this reply (smile, encouraging, serious, …): sets the voice's tone in audio mode.
  final String emotion;
  Answer(this.qaId, this.answer, this.followUp, this.origin, this.sources, this.language, this.access,
      {this.verifyCode = '', this.faculty, this.switched = false, this.handover = '', this.emotion = 'smile'});
  factory Answer.fromJson(Map<String, dynamic> j) => Answer(
        (j['qa_id'] as num).toInt(),
        j['answer'] as String? ?? '',
        j['follow_up'] as String? ?? '',
        j['origin'] as String? ?? 'general_ai',
        ((j['sources'] as List?) ?? []).map((s) => (s as Map)['title'].toString()).toList(),
        j['language'] as String? ?? 'en',
        Access.fromJson(j),
        verifyCode: j['verify_code'] as String? ?? '',
        faculty: Faculty.fromJson(j['faculty']),
        switched: j['switched'] == true,
        handover: j['handover'] as String? ?? '',
        emotion: j['emotion'] as String? ?? 'smile',
      );
}

class SavedNote {
  final int id;
  final int? qaId; // kind == 'answer': the one answer saved
  final String title;
  final String createdAt;
  final String kind; // answer | class (notes of a whole class, topic-wise)
  final List<String> topics;
  SavedNote(this.id, this.qaId, this.title, this.createdAt, {this.kind = 'answer', this.topics = const []});
  factory SavedNote.fromJson(Map<String, dynamic> j) => SavedNote(
        (j['id'] as num).toInt(),
        (j['qa_id'] as num?)?.toInt(),
        j['title'] as String,
        j['created_at']?.toString() ?? '',
        kind: j['kind'] as String? ?? 'answer',
        topics: ((j['topics'] as List?) ?? []).map((t) => t.toString()).toList(),
      );
}

/// One topic taught in a class (greetings and small talk are left out by the server).
class ClassTopic {
  final String topic;
  final int questions;
  ClassTopic(this.topic, this.questions);
}

/// The class in progress (or just ended): its topics, its notes, and whether Sir can give a test.
class ClassSummary {
  final int? sessionId;
  final List<ClassTopic> topics;
  final int? notesId;
  final bool canTest;
  ClassSummary(this.sessionId, this.topics, this.notesId, this.canTest);
  factory ClassSummary.fromJson(Map<String, dynamic> j) => ClassSummary(
        (j['session_id'] as num?)?.toInt(),
        ((j['topics'] as List?) ?? [])
            .map((t) => ClassTopic((t as Map)['topic'].toString(), ((t['questions'] as num?) ?? 0).toInt()))
            .toList(),
        (j['notes_id'] as num?)?.toInt(),
        j['can_test'] == true,
      );
}

/// Test series. mode: mcq | written | oral.
const testModes = {'mcq': 'MCQ', 'written': 'Written', 'oral': 'Oral (viva)'};

class TestQuestion {
  final String q;
  final List<String> options; // empty for written / oral
  TestQuestion(this.q, this.options);
}

class TestResult {
  final String outcome; // praise | good | reteach_offer
  final double score;
  final int total;
  final int percent;
  final List<String> weakTopics;
  final String message;
  TestResult(this.outcome, this.score, this.total, this.percent, this.weakTopics, this.message);
  factory TestResult.fromJson(Map<String, dynamic> j) => TestResult(
        j['outcome'] as String? ?? 'good',
        ((j['score'] as num?) ?? 0).toDouble(),
        ((j['total'] as num?) ?? 0).toInt(),
        ((j['percent'] as num?) ?? 0).toInt(),
        ((j['weak_topics'] as List?) ?? []).map((t) => t.toString()).toList(),
        j['message'] as String? ?? '',
      );
  String get scoreText => '${score == score.roundToDouble() ? score.toInt() : score}/$total';
}

class TestState {
  final int id;
  final String mode;
  final int total;
  final int index;
  final bool done;
  final List<String> topics;
  final TestQuestion? question;
  final TestResult? result;
  /// Multi-teacher: the teacher who gives this test (who taught most of the class); null = the app's teacher.
  final String? teacherName;
  TestState(this.id, this.mode, this.total, this.index, this.done, this.topics, this.question, this.result,
      {this.teacherName});
  factory TestState.fromJson(Map<String, dynamic> j) {
    final q = j['question'] as Map<String, dynamic>?;
    final r = j['result'] as Map<String, dynamic>?;
    return TestState(
      (j['id'] as num).toInt(),
      j['mode'] as String,
      (j['total'] as num).toInt(),
      (j['index'] as num).toInt(),
      j['status'] == 'done',
      ((j['topics'] as List?) ?? []).map((t) => t.toString()).toList(),
      q == null ? null : TestQuestion(q['q'] as String, ((q['options'] as List?) ?? []).map((o) => o.toString()).toList()),
      r == null ? null : TestResult.fromJson(r),
      teacherName: Faculty.fromJson(j['faculty'])?.name,
    );
  }
}

/// Sir's check of one answer, and the test after it (next question, or the result).
class AnswerCheck {
  final bool correct;
  final double score;
  final String feedback;
  final String correctAnswer;
  final TestState test;
  AnswerCheck(this.correct, this.score, this.feedback, this.correctAnswer, this.test);
  factory AnswerCheck.fromJson(Map<String, dynamic> j) => AnswerCheck(
        j['correct'] == true,
        ((j['score'] as num?) ?? 0).toDouble(),
        j['feedback'] as String? ?? '',
        j['correct_answer']?.toString() ?? '',
        TestState.fromJson(j['test'] as Map<String, dynamic>),
      );
}

class HistoryItem {
  final int id;
  final String question;
  final String answer;
  final String createdAt;
  final bool pdfSaved;
  final bool needsReview;
  HistoryItem(this.id, this.question, this.answer, this.createdAt, this.pdfSaved, this.needsReview);
  factory HistoryItem.fromJson(Map<String, dynamic> j) => HistoryItem(
        (j['id'] as num).toInt(),
        j['question'] as String,
        j['answer'] as String,
        j['created_at']?.toString() ?? '',
        j['pdf_saved'] == true,
        j['needs_review'] == 1 || j['needs_review'] == true,
      );
}

/// One screenful of My Library: the latest few notes + one page of history, with totals.
class Library {
  final List<SavedNote> notes;
  final int notesTotal;
  final List<HistoryItem> history;
  final int historyTotal;
  Library(this.notes, this.notesTotal, this.history, this.historyTotal);
}

class NotesPage {
  final List<SavedNote> items;
  final int total;
  NotesPage(this.items, this.total);
}

class Checkout {
  final String keyId;
  final String orderId;
  final int amount;
  final String planName;
  Checkout(this.keyId, this.orderId, this.amount, this.planName);
}

class Receipt {
  final String plan;
  final int amountPaise;
  final DateTime validTill;
  final String paymentId;
  Receipt(this.plan, this.amountPaise, this.validTill, this.paymentId);
  factory Receipt.fromJson(Map<String, dynamic> j) => Receipt(
        j['plan'] as String,
        (j['amount_paise'] as num).toInt(),
        DateTime.fromMillisecondsSinceEpoch(((j['valid_till'] as num) * 1000).toInt()),
        j['payment_id'] as String,
      );
}

/// What the screens need from the backend. [HttpApi] talks to the real server; [DemoApi] works offline.
abstract class Api {
  /// Full address of a picture the server gives as a path (teacher photos); null in the offline demo.
  String? mediaUrl(String? path);
  bool get isDemo;
  Future<List<Plan>> plans();
  Future<void> sendOtp(String phone);
  /// Wakes the server up while the student types the number (a sleeping server takes up to a minute).
  Future<void> warmUp();
  Future<Access> verifyOtp(String phone, String code);
  Future<bool> hasSession();
  Future<Access> access();
  /// B1: class + "18 or older?"; then, for under-18s, the parent's code.
  Future<Access> setProfile(String classLevel, bool isAdult);
  Future<void> sendParentOtp(String phone);
  Future<Access> verifyParentOtp(String phone, String code);
  Future<Answer> ask(String question);
  Future<SavedNote> saveNote(int qaId); // older single-answer notes (kept for compatibility)
  /// Notes of the whole class so far, one PDF per class. [topics] null = all topics of the class.
  Future<SavedNote> saveClassNotes({List<String>? topics});
  Future<ClassSummary> currentClass();
  Future<ClassSummary> endClass();
  Future<TestState> startTest(String mode, {List<String>? topics, int? sessionId});
  /// MCQ: the option index; written / oral: the student's answer text.
  Future<AnswerCheck> answerTest(int testId, Object answer);
  /// "Shall I teach it again?" — yes returns Sir's new explanation, no returns null.
  Future<Answer?> reteach(int testId, bool yes);
  Future<String> shareUrl();
  Future<Uint8List> notePdf(int noteId);
  Future<Library> library({String query = '', int historyOffset = 0});
  Future<NotesPage> notes({int offset = 0, int limit = 20, String query = ''});
  Future<Checkout> checkout(String planId);
  Future<Receipt> confirmPayment(String orderId, String paymentId, String signature);
  Future<void> logout();
  /// B6: deletes the account and learning data on the server (can't be undone), then logs out.
  Future<void> deleteMyData();
  /// Profile: the account, "What should Sir call you?", and changing the mobile number (code on the new number).
  Future<Me> me();
  Future<void> setName(String name);
  Future<void> changePhoneOtp(String phone);
  Future<String> changePhoneVerify(String phone, String code);

  static Api create(TeacherConfig cfg) => apiBaseUrl.isEmpty ? DemoApi(cfg) : HttpApi(apiBaseUrl, cfg.teacherId);
}

class HttpApi implements Api {
  final String base;
  final String teacherId;
  String? _token;
  HttpApi(this.base, this.teacherId);

  @override
  bool get isDemo => false;

  @override
  String? mediaUrl(String? path) =>
      path == null || path.isEmpty ? null : (path.startsWith('http') ? path : '$base${path.startsWith('/') ? '' : '/'}$path');

  Future<String?> _loadToken() async {
    _token ??= (await SharedPreferences.getInstance()).getString('token');
    return _token;
  }

  String? _deviceId;

  /// A random id made once per install (no personal data). The server uses it to limit OTP requests per phone.
  Future<String> _loadDeviceId() async {
    if (_deviceId != null) return _deviceId!;
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString('device_id');
    if (id == null) {
      final r = Random.secure();
      id = List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
      await prefs.setString('device_id', id);
    }
    return _deviceId = id;
  }

  Future<dynamic> _call(String method, String path, [Map<String, dynamic>? body]) async {
    final token = await _loadToken();
    final headers = {
      'Content-Type': 'application/json',
      'X-Teacher-Id': teacherId,
      'X-Device-Id': await _loadDeviceId(),
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final uri = Uri.parse('$base$path');
    final res = method == 'GET'
        ? await http.get(uri, headers: headers)
        : method == 'PUT'
            ? await http.put(uri, headers: headers, body: jsonEncode(body ?? {}))
            : await http.post(uri, headers: headers, body: jsonEncode(body ?? {}));
    final data = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 400) {
      final detail = data is Map && data['detail'] is String ? data['detail'] as String : 'Something went wrong';
      throw ApiException(res.statusCode, detail);
    }
    return data;
  }

  @override
  Future<List<Plan>> plans() async {
    final j = await _call('GET', '/teacher') as Map<String, dynamic>;
    return (j['plans'] as List).map((p) => Plan.fromJson(p as Map<String, dynamic>)).toList();
  }

  @override
  Future<void> sendOtp(String phone) async {
    await _call('POST', '/auth/otp', {'phone': phone});
  }

  @override
  Future<Access> verifyOtp(String phone, String code) async {
    final j = await _call('POST', '/auth/verify', {'phone': phone, 'code': code}) as Map<String, dynamic>;
    _token = j['token'] as String;
    await (await SharedPreferences.getInstance()).setString('token', _token!);
    return Access.fromJson(j);
  }

  @override
  Future<bool> hasSession() async => (await _loadToken()) != null;

  @override
  Future<Access> access() async => Access.fromJson(await _call('GET', '/me/access') as Map<String, dynamic>);

  @override
  Future<void> warmUp() async {
    try {
      await http.get(Uri.parse('$base/health')).timeout(const Duration(seconds: 90));
    } catch (_) {} // only a wake-up call; errors don't matter
  }

  @override
  Future<Access> setProfile(String classLevel, bool isAdult) async => Access.fromJson(
      await _call('PUT', '/me/profile', {'class_level': classLevel, 'is_adult': isAdult}) as Map<String, dynamic>);

  @override
  Future<void> sendParentOtp(String phone) async {
    await _call('POST', '/me/parent/otp', {'phone': phone});
  }

  @override
  Future<Access> verifyParentOtp(String phone, String code) async => Access.fromJson(
      await _call('POST', '/me/parent/verify', {'phone': phone, 'code': code}) as Map<String, dynamic>);

  @override
  Future<Answer> ask(String question) async {
    final j = await _call('POST', '/class/ask', {'question': question}) as Map<String, dynamic>;
    // the app handles "save this" / "test lo" itself; if the server still sees one, ask the screen to do it
    if (j['type'] == 'note_saved') throw CommandException('save');
    if (j['type'] == 'test_offer') throw CommandException('test');
    if (j['type'] == 'delete_offer') throw CommandException('delete');
    if (j['type'] == 'profile') throw CommandException('profile');
    return Answer.fromJson(j);
  }

  @override
  Future<SavedNote> saveNote(int qaId) async =>
      SavedNote.fromJson(await _call('POST', '/notes/$qaId') as Map<String, dynamic>);

  @override
  Future<SavedNote> saveClassNotes({List<String>? topics}) async =>
      SavedNote.fromJson(await _call('POST', '/class/notes', {'topics': topics}) as Map<String, dynamic>);

  @override
  Future<ClassSummary> currentClass() async =>
      ClassSummary.fromJson(await _call('GET', '/class/current') as Map<String, dynamic>);

  @override
  Future<ClassSummary> endClass() async =>
      ClassSummary.fromJson(await _call('POST', '/class/end') as Map<String, dynamic>);

  @override
  Future<TestState> startTest(String mode, {List<String>? topics, int? sessionId}) async => TestState.fromJson(
      await _call('POST', '/tests', {'mode': mode, 'topics': topics, 'session_id': sessionId}) as Map<String, dynamic>);

  @override
  Future<AnswerCheck> answerTest(int testId, Object answer) async =>
      AnswerCheck.fromJson(await _call('POST', '/tests/$testId/answer', {'answer': answer}) as Map<String, dynamic>);

  @override
  Future<Answer?> reteach(int testId, bool yes) async {
    final j = await _call('POST', '/tests/$testId/reteach', {'yes': yes}) as Map<String, dynamic>;
    return j['type'] == 'answer' ? Answer.fromJson(j) : null;
  }

  String? _shareUrl;

  @override
  Future<String> shareUrl() async {
    _shareUrl ??= ((await _call('GET', '/teacher') as Map<String, dynamic>)['share_url'] as String?) ?? '';
    return _shareUrl!;
  }

  @override
  Future<Uint8List> notePdf(int noteId) async {
    final token = await _loadToken();
    final res = await http.get(Uri.parse('$base/notes/$noteId/pdf'),
        headers: {'X-Teacher-Id': teacherId, if (token != null) 'Authorization': 'Bearer $token'});
    if (res.statusCode >= 400) throw ApiException(res.statusCode, 'Could not download the PDF');
    return res.bodyBytes;
  }

  @override
  Future<Library> library({String query = '', int historyOffset = 0}) async {
    final q = Uri.encodeQueryComponent(query);
    final j = await _call('GET', '/library?q=$q&history_offset=$historyOffset') as Map<String, dynamic>;
    return Library(
      (j['saved_notes'] as List).map((n) => SavedNote.fromJson(n as Map<String, dynamic>)).toList(),
      (j['notes_total'] as num).toInt(),
      (j['history'] as List).map((h) => HistoryItem.fromJson(h as Map<String, dynamic>)).toList(),
      (j['history_total'] as num).toInt(),
    );
  }

  @override
  Future<NotesPage> notes({int offset = 0, int limit = 20, String query = ''}) async {
    final q = Uri.encodeQueryComponent(query);
    final j = await _call('GET', '/notes?offset=$offset&limit=$limit&q=$q') as Map<String, dynamic>;
    return NotesPage((j['items'] as List).map((n) => SavedNote.fromJson(n as Map<String, dynamic>)).toList(),
        (j['total'] as num).toInt());
  }

  @override
  Future<Checkout> checkout(String planId) async {
    final j = await _call('POST', '/pay/checkout', {'plan_id': planId}) as Map<String, dynamic>;
    return Checkout(j['key_id'] as String, j['order_id'] as String, (j['amount'] as num).toInt(), j['plan_name'] as String);
  }

  @override
  Future<Receipt> confirmPayment(String orderId, String paymentId, String signature) async =>
      Receipt.fromJson(await _call('POST', '/pay/confirm', {
        'razorpay_order_id': orderId,
        'razorpay_payment_id': paymentId,
        'razorpay_signature': signature,
      }) as Map<String, dynamic>);

  @override
  Future<Me> me() async => Me.fromJson(await _call('GET', '/me') as Map<String, dynamic>);

  @override
  Future<void> setName(String name) async => _call('PUT', '/me/name', {'name': name});

  @override
  Future<void> changePhoneOtp(String phone) async => _call('POST', '/me/phone/otp', {'phone': phone});

  @override
  Future<String> changePhoneVerify(String phone, String code) async =>
      ((await _call('POST', '/me/phone/verify', {'phone': phone, 'code': code}) as Map)['phone']).toString();

  @override
  Future<void> logout() async {
    _token = null;
    await (await SharedPreferences.getInstance()).remove('token');
  }

  @override
  Future<void> deleteMyData() async {
    await _call('POST', '/me/delete', {'confirm': 'DELETE'});
    await logout();
  }
}

/// Offline demo: lets anyone install the APK and click through every screen without a server.
class DemoApi implements Api {
  final TeacherConfig cfg;
  DemoApi(this.cfg);

  int _demoUsed = 0;
  bool _subscribed = false;
  late final Faculty _demoOwn = Faculty(1, cfg.teacherName, subjects: [cfg.subject]);
  final Faculty _demoMaths = const Faculty(2, 'Gupta Sir', subjects: ['Mathematics']);
  late Faculty _demoTeacher = _demoOwn;
  String? _simulated; // demo-only: preview renew-soon / grace / expired screens
  int _graceUsed = 0;
  bool _loggedIn = false;
  int _nextId = 1;
  final List<HistoryItem> _history = [];
  final List<SavedNote> _notes = [];
  final List<String> _classTopics = []; // what the current demo class has covered
  List<String> _lastClassTopics = [];
  int _classNo = 1;
  final Map<int, _DemoTest> _tests = {};

  @override
  bool get isDemo => true;

  @override
  String? mediaUrl(String? path) => null;

  Access get _access {
    final ended = DateTime.now().subtract(const Duration(hours: 1));
    switch (_simulated) {
      case 'renew':
        return Access('active', 0, daysLeft: 2, renewSoon: true);
      case 'grace':
        return 3 - _graceUsed > 0
            ? Access('grace', 0, planEndedAt: ended, graceLeft: 3 - _graceUsed)
            : Access('expired', 0, planEndedAt: ended);
      case 'expired':
        return Access('expired', 0, planEndedAt: ended);
    }
    return _subscribed ? Access('active', 0, daysLeft: 364) : Access('demo', 3 - _demoUsed);
  }

  /// Demo mode only: long-press the class timer to preview what happens when a plan runs out.
  Access simulateNext() {
    const order = [null, 'renew', 'grace', 'expired'];
    _simulated = order[(order.indexOf(_simulated) + 1) % order.length];
    _graceUsed = 0;
    return _access;
  }

  @override
  Future<List<Plan>> plans() async =>
      [Plan('monthly', 'Monthly', 0, 30), Plan('yearly', 'Yearly', 0, 365)];

  @override
  Future<void> sendOtp(String phone) async {
    await Future.delayed(const Duration(milliseconds: 500));
  }

  // B1 in demo mode: the class and parent steps are shown, any code works
  String? _classLevel;
  bool _adult = false;
  bool _parentOk = false;
  Access get _now => _access.withSetup(
      profileNeeded: _classLevel == null, consentNeeded: _classLevel != null && !_adult && !_parentOk);

  @override
  Future<Access> verifyOtp(String phone, String code) async {
    await Future.delayed(const Duration(milliseconds: 500));
    _loggedIn = true;
    return _now;
  }

  @override
  Future<Access> setProfile(String classLevel, bool isAdult) async {
    _classLevel = classLevel;
    _adult = isAdult;
    return _now;
  }

  @override
  Future<void> sendParentOtp(String phone) async => Future.delayed(const Duration(milliseconds: 400));

  @override
  Future<void> warmUp() async {}

  @override
  Future<Access> verifyParentOtp(String phone, String code) async {
    await Future.delayed(const Duration(milliseconds: 400));
    _parentOk = true;
    return _now;
  }

  @override
  Future<bool> hasSession() async => _loggedIn;

  @override
  Future<Access> access() async => _now;

  @override
  Future<Answer> ask(String question) async {
    await Future.delayed(const Duration(milliseconds: 900));
    final st = _access.state;
    if (st == 'expired') {
      throw ApiException(402, 'Your plan has ended. Renew to continue learning with ${cfg.teacherName}.');
    } else if (st == 'grace') {
      _graceUsed++;
    } else if (st == 'demo') {
      if (_demoUsed >= 3) {
        throw ApiException(402, 'Your free demo questions are over. Subscribe to keep learning with ${cfg.teacherName}.');
      }
      _demoUsed++;
    }
    final hindi = RegExp(r'[ऀ-ॿ]').hasMatch(question);
    final punjabi = RegExp(r'[਀-੿]').hasMatch(question);
    final answer = punjabi
        ? 'ਇਹ ਡੈਮੋ ਜਵਾਬ ਹੈ। ਸਰਵਰ ਜੁੜਨ ਤੋਂ ਬਾਅਦ ${cfg.teacherName} ਆਪਣੇ ਨੋਟਸ ਤੋਂ ਜਵਾਬ ਦੇਣਗੇ।'
        : hindi
            ? 'यह डेमो जवाब है। सर्वर जुड़ने के बाद ${cfg.teacherName} अपने नोट्स से जवाब देंगे।'
            : 'This is a demo answer. Once the server is connected, ${cfg.teacherName} will answer from his own notes.';
    final follow = punjabi ? 'ਕੀ ਤੁਸੀਂ ਸਮਝ ਗਏ?' : hindi ? 'क्या आप समझ गए?' : 'Did that make sense? Tell me in one line.';
    final id = _nextId++;
    _history.insert(0, HistoryItem(id, question, answer, DateTime.now().toString(), false, false));
    final topic = question.length > 50 ? '${question.substring(0, 50)}…' : question;
    if (!_classTopics.contains(topic)) _classTopics.add(topic);
    // demo of multi-teacher switching: a maths question (or "maths wale sir ko bulao") goes to a second teacher
    final low = question.toLowerCase();
    final maths = RegExp(r'math|ganit|गणित|percent|प्रतिशत|ज्यामिति|algebra|\d+\s*[x×+*/-]\s*\d+').hasMatch(low);
    final back = RegExp(r'history|itihas|इतिहास|haldighati|हल्दीघाटी|rajasthan|राजस्थान').hasMatch(low);
    final before = _demoTeacher;
    if (maths) _demoTeacher = _demoMaths;
    if (back && !maths) _demoTeacher = _demoOwn;
    final switched = before.id != _demoTeacher.id;
    final handover = !switched ? '' : hindi
        ? 'यह ${_demoTeacher.subjects.first} का सवाल है — मैं आपको ${_demoTeacher.name} से जोड़ रहा हूँ।'
        : 'This is a ${_demoTeacher.subjects.first} question — let me connect you to ${_demoTeacher.name}.';
    return Answer(id, answer, follow, 'teacher_notes', ["Sir’s notes"], hindi ? 'hi' : punjabi ? 'pa' : 'en', _access,
        faculty: _demoTeacher, switched: switched, handover: handover);
  }

  @override
  Future<SavedNote> saveNote(int qaId) async {
    await Future.delayed(const Duration(milliseconds: 400));
    final i = _history.indexWhere((h) => h.id == qaId);
    final h = _history[i];
    _history[i] = HistoryItem(h.id, h.question, h.answer, h.createdAt, true, h.needsReview);
    final note = SavedNote(_notes.length + 1, qaId, h.question, h.createdAt);
    _notes.insert(0, note);
    return note;
  }

  List<String> get _topicsForTest => _classTopics.isNotEmpty ? _classTopics : _lastClassTopics;

  ClassSummary _summary(List<String> topics) =>
      ClassSummary(topics.isEmpty ? null : _classNo, topics.map((t) => ClassTopic(t, 1)).toList(),
          _notes.where((n) => n.kind == 'class' && n.qaId == -_classNo).map((n) => n.id).firstOrNull, topics.isNotEmpty);

  @override
  Future<SavedNote> saveClassNotes({List<String>? topics}) async {
    await Future.delayed(const Duration(milliseconds: 500));
    final all = _topicsForTest;
    if (all.isEmpty) throw ApiException(400, 'Nothing to save yet — ask Sir something about your studies first.');
    final chosen = topics == null ? all : all.where(topics.contains).toList();
    // one note per class: saving again updates it (qaId = -class number marks the demo class)
    _notes.removeWhere((n) => n.kind == 'class' && n.qaId == -_classNo);
    final note = SavedNote(_notes.length + 1, -_classNo, 'Class notes · ${chosen.first}', DateTime.now().toString(),
        kind: 'class', topics: chosen);
    _notes.insert(0, note);
    return note;
  }

  @override
  Future<ClassSummary> currentClass() async => _summary(_classTopics);

  @override
  Future<ClassSummary> endClass() async {
    final s = _summary(_classTopics);
    if (_classTopics.isNotEmpty) _lastClassTopics = List.of(_classTopics);
    _classTopics.clear();
    _classNo++;
    return s;
  }

  @override
  Future<TestState> startTest(String mode, {List<String>? topics, int? sessionId}) async {
    await Future.delayed(const Duration(milliseconds: 700));
    final from = topics ?? _topicsForTest;
    if (from.isEmpty) throw ApiException(400, 'Study a topic with Sir first — then he can test you on it.');
    final t = _DemoTest(_tests.length + 1, mode, from);
    _tests[t.id] = t;
    return t.state();
  }

  @override
  Future<AnswerCheck> answerTest(int testId, Object answer) async {
    await Future.delayed(const Duration(milliseconds: 400));
    return _tests[testId]!.answer(answer, cfg.teacherName);
  }

  @override
  Future<Answer?> reteach(int testId, bool yes) async {
    if (!yes) return null;
    return ask('Sir, please teach me again: ${_tests[testId]!.topics.take(3).join(', ')}');
  }

  @override
  Future<String> shareUrl() async => cfg.shareUrl;

  @override
  Future<Uint8List> notePdf(int noteId) async =>
      throw ApiException(0, 'PDFs can be shared once the app is connected to the server.');

  bool _match(String text, String q) => q.isEmpty || text.toLowerCase().contains(q.toLowerCase());

  @override
  Future<Library> library({String query = '', int historyOffset = 0}) async {
    final notes = _notes.where((n) => _match(n.title, query)).toList();
    final hist = _history.where((h) => _match(h.question, query) || _match(h.answer, query)).toList();
    return Library(notes.take(10).toList(), notes.length, hist.skip(historyOffset).take(30).toList(), hist.length);
  }

  @override
  Future<NotesPage> notes({int offset = 0, int limit = 20, String query = ''}) async {
    final notes = _notes.where((n) => _match(n.title, query)).toList();
    return NotesPage(notes.skip(offset).take(limit).toList(), notes.length);
  }

  @override
  Future<Checkout> checkout(String planId) async =>
      Checkout('demo', 'order_demo_${DateTime.now().millisecondsSinceEpoch}', 0, planId == 'yearly' ? 'Yearly' : 'Monthly');

  @override
  Future<Receipt> confirmPayment(String orderId, String paymentId, String signature) async {
    _subscribed = true;
    _simulated = null;
    return Receipt('Yearly', 0, DateTime.now().add(const Duration(days: 365)), paymentId);
  }

  String _name = '';
  String _phone = '+919876543210';

  @override
  Future<Me> me() async => Me(_name, _phone, '10', 'given', false, _access);

  @override
  Future<void> setName(String name) async => _name = name.trim();

  @override
  Future<void> changePhoneOtp(String phone) async {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length != 10) throw ApiException(400, 'Enter a valid 10-digit mobile number');
  }

  @override
  Future<String> changePhoneVerify(String phone, String code) async {
    if (code.trim() != '123456') throw ApiException(400, 'Wrong code. In the demo the code is 123456.');
    return _phone = '+91${phone.replaceAll(RegExp(r'\D'), '')}';
  }

  @override
  Future<void> logout() async {
    _loggedIn = false;
  }

  @override
  Future<void> deleteMyData() async {
    _history.clear();
    _notes.clear();
    _classLevel = null;
    _parentOk = false;
    _loggedIn = false;
  }
}

/// Demo-mode test: 5 sample questions so the screens can be tried without a server.
class _DemoTest {
  final int id;
  final String mode;
  final List<String> topics;
  int index = 0;
  double score = 0;
  final List<String> weak = [];
  TestResult? result;
  late final List<int> _right = List.generate(total, (i) => Random(id * 31 + i).nextInt(4));
  _DemoTest(this.id, this.mode, this.topics);

  int get total => 5;
  String _topic(int i) => topics[i % topics.length];

  TestQuestion _q(int i) => mode == 'mcq'
      ? TestQuestion('Demo question ${i + 1} on “${_topic(i)}”: which option is correct?',
          List.generate(4, (k) => k == _right[i] ? 'The correct answer' : 'Wrong answer ${k + 1}'))
      : TestQuestion('Demo question ${i + 1}: explain “${_topic(i)}” in two or three lines.', const []);

  TestState state() => TestState(id, mode, total, index, result != null, topics, result == null ? _q(index) : null, result);

  AnswerCheck answer(Object a, String teacher) {
    final i = index;
    double s;
    String correctAnswer;
    if (mode == 'mcq') {
      s = a == _right[i] ? 1.0 : 0.0;
      correctAnswer = 'The correct answer';
    } else {
      final words = a.toString().trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length;
      s = words >= 8 ? 1.0 : words >= 3 ? 0.5 : 0.0;
      correctAnswer = 'Sir’s model answer appears here once the server is connected.';
    }
    score += s;
    if (s < 1 && !weak.contains(_topic(i))) weak.add(_topic(i));
    if (index + 1 >= total) {
      final pct = (score / total * 100).round();
      final outcome = pct < 50 ? 'reteach_offer' : pct >= 80 ? 'praise' : 'good';
      final st = '${score == score.roundToDouble() ? score.toInt() : score}/$total';
      final names = (weak.isEmpty ? topics : weak).take(4).join(', ');
      final msg = outcome == 'praise'
          ? 'Shabash! $st correct ($pct%). Excellent work — keep it up!'
          : outcome == 'good'
              ? 'Good, $st correct ($pct%). Revise these once more: $names. We\'ll continue from here tomorrow.'
              : '$st correct ($pct%). Most answers were wrong — no problem. Shall I teach $names again now?';
      result = TestResult(outcome, score, total, pct, List.of(weak), msg);
    } else {
      index++;
    }
    final feedback = mode == 'mcq' ? '' : (s == 1 ? 'Well explained!' : s > 0 ? 'Partly right — add a little more.' : 'Not quite.');
    return AnswerCheck(s == 1, s, feedback, correctAnswer, state());
  }
}
