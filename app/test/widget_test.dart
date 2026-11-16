import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liveteach/api.dart';
import 'package:liveteach/config.dart';
import 'package:liveteach/main.dart';

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
    expect(find.text('AI call with your teacher, anytime.'), findsOneWidget);
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
}
