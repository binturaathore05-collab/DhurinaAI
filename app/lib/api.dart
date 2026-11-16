import 'dart:convert';

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
  Access(this.state, this.demoLeft, {this.daysLeft, this.renewSoon = false, this.planEndedAt, this.graceLeft = 0});

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
    );
  }
}

class Answer {
  final int qaId;
  final String answer;
  final String followUp;
  final String origin; // verified | teacher_notes | general_ai
  final List<String> sources;
  final String language;
  final Access access;
  Answer(this.qaId, this.answer, this.followUp, this.origin, this.sources, this.language, this.access);
  factory Answer.fromJson(Map<String, dynamic> j) => Answer(
        (j['qa_id'] as num).toInt(),
        j['answer'] as String? ?? '',
        j['follow_up'] as String? ?? '',
        j['origin'] as String? ?? 'general_ai',
        ((j['sources'] as List?) ?? []).map((s) => (s as Map)['title'].toString()).toList(),
        j['language'] as String? ?? 'en',
        Access.fromJson(j),
      );
}

class SavedNote {
  final int id;
  final int qaId;
  final String title;
  final String createdAt;
  SavedNote(this.id, this.qaId, this.title, this.createdAt);
  factory SavedNote.fromJson(Map<String, dynamic> j) =>
      SavedNote((j['id'] as num).toInt(), (j['qa_id'] as num).toInt(), j['title'] as String, j['created_at']?.toString() ?? '');
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
  bool get isDemo;
  Future<List<Plan>> plans();
  Future<void> sendOtp(String phone);
  Future<Access> verifyOtp(String phone, String code);
  Future<bool> hasSession();
  Future<Access> access();
  Future<Answer> ask(String question);
  Future<SavedNote> saveNote(int qaId);
  Future<Library> library({String query = '', int historyOffset = 0});
  Future<NotesPage> notes({int offset = 0, int limit = 20, String query = ''});
  Future<Checkout> checkout(String planId);
  Future<Receipt> confirmPayment(String orderId, String paymentId, String signature);
  Future<void> logout();

  static Api create(TeacherConfig cfg) => apiBaseUrl.isEmpty ? DemoApi(cfg) : HttpApi(apiBaseUrl, cfg.teacherId);
}

class HttpApi implements Api {
  final String base;
  final String teacherId;
  String? _token;
  HttpApi(this.base, this.teacherId);

  @override
  bool get isDemo => false;

  Future<String?> _loadToken() async {
    _token ??= (await SharedPreferences.getInstance()).getString('token');
    return _token;
  }

  Future<dynamic> _call(String method, String path, [Map<String, dynamic>? body]) async {
    final token = await _loadToken();
    final headers = {
      'Content-Type': 'application/json',
      'X-Teacher-Id': teacherId,
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final uri = Uri.parse('$base$path');
    final res = method == 'GET'
        ? await http.get(uri, headers: headers)
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
  Future<Answer> ask(String question) async =>
      Answer.fromJson(await _call('POST', '/class/ask', {'question': question}) as Map<String, dynamic>);

  @override
  Future<SavedNote> saveNote(int qaId) async =>
      SavedNote.fromJson(await _call('POST', '/notes/$qaId') as Map<String, dynamic>);

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
  Future<void> logout() async {
    _token = null;
    await (await SharedPreferences.getInstance()).remove('token');
  }
}

/// Offline demo: lets anyone install the APK and click through every screen without a server.
class DemoApi implements Api {
  final TeacherConfig cfg;
  DemoApi(this.cfg);

  int _demoUsed = 0;
  bool _subscribed = false;
  String? _simulated; // demo-only: preview renew-soon / grace / expired screens
  int _graceUsed = 0;
  bool _loggedIn = false;
  int _nextId = 1;
  final List<HistoryItem> _history = [];
  final List<SavedNote> _notes = [];

  @override
  bool get isDemo => true;

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

  @override
  Future<Access> verifyOtp(String phone, String code) async {
    await Future.delayed(const Duration(milliseconds: 500));
    _loggedIn = true;
    return _access;
  }

  @override
  Future<bool> hasSession() async => _loggedIn;

  @override
  Future<Access> access() async => _access;

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
    return Answer(id, answer, follow, 'teacher_notes', ["Sir’s notes"], hindi ? 'hi' : punjabi ? 'pa' : 'en', _access);
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

  @override
  Future<void> logout() async {
    _loggedIn = false;
  }
}
