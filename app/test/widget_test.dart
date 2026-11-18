import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liveteach/api.dart';
import 'package:liveteach/config.dart';
import 'package:liveteach/main.dart';
import 'package:liveteach/screens/live_screen.dart';
import 'package:liveteach/theme.dart';
import 'package:liveteach/voice.dart';
import 'package:liveteach/screens/profile_screen.dart';

void main() {
  const cfg = TeacherConfig(
    teacherId: 'demo',
    appName: 'Test Teacher AI',
    teacherName: 'Test Sir',
    subject: 'History',
    avatar: 'assets/teacher/avatar.jpg',
    accent: Color(0xFF2DD4BF),
  );

  testWidgets('login screen shows the teacher and the demo button', (tester) async {
    await tester.pumpWidget(LiveTeachApp(cfg: cfg, api: DemoApi(cfg), loggedIn: false));
    expect(find.text('Call your AI teacher, anytime.'), findsOneWidget);
    expect(find.text('Start free demo call'), findsOneWidget);
    expect(find.textContaining('Test Sir is available now'), findsOneWidget);
  });

  test('demo api: three free questions, save notes, then subscribe', () async {
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    final a = await api.ask('हल्दीघाटी का युद्ध कब हुआ?');
    expect(a.language, 'hi');
    await api.saveNote(a.qaId);
    expect((await api.library()).notes.length, 1);
    await api.ask('Q2');
    await api.ask('Q3');
    await expectLater(api.ask('Q4'), throwsA(isA<ApiException>()));
    await api.confirmPayment('o', 'p', 's');
    expect((await api.access()).subscribed, true);
  });

  test('demo api: plan ending, grace questions, then expired until renewal', () async {
    final api = DemoApi(cfg);
    expect(api.simulateNext().renewSoon, true);
    expect(api.simulateNext().state, 'grace');
    await api.ask('Q1');
    await api.ask('Q2');
    await api.ask('Q3');
    expect((await api.access()).state, 'expired');
    await expectLater(api.ask('Q4'), throwsA(isA<ApiException>()));
    await api.confirmPayment('o', 'p', 's');
    expect((await api.access()).state, 'active');
  });

  testWidgets('risky actions ask first: Cancel keeps things, confirm goes ahead', (tester) async {
    final results = <bool>[];
    await tester.pumpWidget(MaterialApp(home: Builder(builder: (context) => TextButton(
        onPressed: () async => results.add(await confirmAction(context,
            title: 'End this class?', message: 'Notes stay safe.', confirmLabel: 'End class', danger: true)),
        child: const Text('end')))));
    await tester.tap(find.text('end'));
    await tester.pumpAndSettle();
    expect(find.text('End this class?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('end'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('End class'));
    await tester.pumpAndSettle();
    expect(results, [false, true]);
  });

  test('demo api: whole-class notes update in place, topics can be chosen', () async {
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    await expectLater(api.saveClassNotes(), throwsA(isA<ApiException>())); // nothing studied yet
    await api.ask('Haldighati');
    await api.ask('Chetak');
    final n1 = await api.saveClassNotes();
    expect(n1.kind, 'class');
    expect(n1.topics, ['Haldighati', 'Chetak']);
    final n2 = await api.saveClassNotes(topics: ['Chetak']);
    expect(n2.topics, ['Chetak']);
    expect((await api.library()).notes.where((n) => n.kind == 'class').length, 1);
    expect((await api.currentClass()).topics.length, 2);
  });

  test('demo api: MCQ test, score, and Sir offers to teach again on a low score', () async {
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    await expectLater(api.startTest('mcq'), throwsA(isA<ApiException>()));
    await api.ask('Haldighati');
    final ended = await api.endClass();
    expect(ended.canTest, true);
    var t = await api.startTest('mcq'); // uses the class that just ended
    expect(t.question!.options.length, 4);
    while (!t.done) {
      final c = await api.answerTest(t.id, 9); // never a real option → all wrong
      t = c.test;
    }
    expect(t.result!.outcome, 'reteach_offer');
    expect(await api.reteach(t.id, false), isNull);
  });

  test('demo api: written test checks answers and praises a full score', () async {
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    await api.ask('Photosynthesis');
    var t = await api.startTest('written');
    expect(t.question!.options, isEmpty);
    while (!t.done) {
      t = (await api.answerTest(t.id, 'Plants make food from sunlight water and carbon dioxide in leaves')).test;
    }
    expect(t.result!.outcome, 'praise');
    expect(t.result!.message, startsWith('Shabash'));
  });

  test('class commands are recognised in many languages', () {
    expect(isTestCommand('Sir test lo'), true);
    expect(isTestCommand('सर टेस्ट लो'), true);
    expect(isTestCommand('What is a test tube?'), false);
    expect(isTestCommand('what does test mean?'), false);
    expect(isTestCommand('Sir, mera test le lo!'), true);
    expect(isSaveCommand('Sir, save this'), true);
    expect(isSaveCommand('सर मुझे इसके नोट्स प्रोवाइड कर दो'), true);
    expect(isSaveCommand('Sir notes de do'), true);
    expect(testModeIn('Sir MCQ test lo'), 'mcq');
    expect(testModeIn('सर मौखिक टेस्ट लो'), 'oral');
    expect(testModeIn('Sir test lo'), isNull);
  });

  test('multi-teacher: answers carry the teacher, a switch carries a handover line', () async {
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    final a = await api.ask('Haldighati kab hua?');
    expect(a.faculty?.name, 'Test Sir');
    expect(a.switched, false);
    final b = await api.ask('Maths wale sir ko bulao, 25 percent kitna hai');
    expect(b.faculty?.name, 'Gupta Sir');
    expect(b.switched, true);
    expect(b.handover, contains('Gupta Sir'));
    expect(api.mediaUrl('/faculty/2/avatar'), isNull); // offline demo: no server photos
  });

  test('multi-teacher: server replies are read (answer, access, test)', () {
    final f = Faculty.fromJson({'id': 3, 'name': 'Gupta Sir', 'avatar_url': '/faculty/3/avatar', 'subjects': ['Mathematics']});
    expect(f!.avatarUrl, '/faculty/3/avatar');
    final a = Answer.fromJson({'qa_id': 1, 'answer': 'x', 'faculty': {'id': 3, 'name': 'Gupta Sir'}, 'switched': true,
        'handover': 'Yeh Maths ka sawal hai', 'state': 'demo', 'demo_questions_left': 2,
        'active_faculty': {'id': 3, 'name': 'Gupta Sir'}});
    expect(a.faculty?.id, 3);
    expect(a.switched, true);
    expect(a.access.activeFaculty?.name, 'Gupta Sir');
    expect(Faculty.fromJson(null), isNull);
    final api = HttpApi('https://x.test', 'demo');
    expect(api.mediaUrl('/faculty/3/avatar'), 'https://x.test/faculty/3/avatar');
    expect(api.mediaUrl(null), isNull);
  });

  test('audio mode: Sir speaks sentence by sentence, in the right phone language', () {
    expect(Voice.sentences('हल्दीघाटी का युद्ध 1576 में हुआ। अकबर की सेना थी! क्या समझे?'),
        ['हल्दीघाटी का युद्ध 1576 में हुआ।', 'अकबर की सेना थी!', 'क्या समझे?']);
    expect(Voice.sentences('Pi is 3.14 roughly. Next point.'), ['Pi is 3.14 roughly.', 'Next point.']);
    expect(Voice.ttsLanguage('hi'), 'hi-IN');
    expect(Voice.ttsLanguage('hi-Latn'), 'en-IN');
    expect(Voice.ttsLanguage('en'), 'en-IN');
    expect(Voice.ttsLanguage('pa'), 'pa-IN');
  });

  test('profile: saying it opens it; the number changes with the code from the new number', () async {
    expect(isProfileCommand('Sir mera profile kholo'), true);
    expect(isProfileCommand('मेरा नंबर बदलो'), true);
    expect(isProfileCommand('What is a profile in maths?'), false);
    final api = DemoApi(cfg);
    await api.verifyOtp('9876543210', '123456');
    await api.setName('Ravi');
    expect((await api.me()).name, 'Ravi');
    await api.changePhoneOtp('9876500009');
    expect(() => api.changePhoneVerify('9876500009', '000000'), throwsA(isA<ApiException>()));
    expect(await api.changePhoneVerify('9876500009', '123456'), '+919876500009');
    expect((await api.me()).phone, '+919876500009');
  });
}
