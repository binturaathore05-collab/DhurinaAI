import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter/material.dart';

/// Everything that makes this build "one teacher's app". To make another teacher's app,
/// change assets/teacher/teacher.json and the avatar image — no code changes.
class TeacherConfig {
  final String teacherId;
  final String appName;
  final String teacherName;
  final String subject;
  final String avatar;
  final Color accent;
  /// The link that goes with everything a student shares (teacher page → Play Store). Empty = ask the server.
  final String shareUrl;

  const TeacherConfig({
    required this.teacherId,
    required this.appName,
    required this.teacherName,
    required this.subject,
    required this.avatar,
    required this.accent,
    this.shareUrl = '',
  });

  static Future<TeacherConfig> load() async {
    final raw = await rootBundle.loadString('assets/teacher/teacher.json');
    final j = jsonDecode(raw) as Map<String, dynamic>;
    return TeacherConfig(
      teacherId: j['teacherId'] as String,
      appName: j['appName'] as String,
      teacherName: j['teacherName'] as String,
      subject: (j['subject'] ?? '') as String,
      avatar: j['avatar'] as String,
      accent: _hex(j['accent'] as String? ?? '#2DD4BF'),
      shareUrl: (j['shareUrl'] ?? '') as String,
    );
  }

  static Color _hex(String hex) {
    final h = hex.replaceAll('#', '');
    return Color(int.parse('FF$h', radix: 16));
  }
}

/// Backend address, given at build time: flutter build apk --dart-define=API_BASE_URL=https://api.example.com
/// Empty = demo mode: the app works offline with sample answers, so it can be tried without a server.
const String apiBaseUrl = String.fromEnvironment('API_BASE_URL');
