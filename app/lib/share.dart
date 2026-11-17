import 'dart:math';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import 'api.dart';
import 'main.dart';

/// Everything a student shares carries the teacher's link (a web page that leads to the app on Play Store).
Future<String> _link(BuildContext context) async {
  try {
    return await AppScope.of(context).api.shareUrl();
  } catch (_) {
    return AppScope.of(context).cfg.shareUrl;
  }
}

String _withLink(String text, String link) => link.isEmpty ? text : '$text\n$link';

void _toast(BuildContext context, String msg) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

/// Share the teacher's app.
Future<void> shareApp(BuildContext context) async {
  final cfg = AppScope.of(context).cfg;
  final link = await _link(context);
  await Share.share(
      _withLink('I study with ${cfg.teacherName}’s AI teacher (${cfg.subject}). Ask anything in Hindi, English or any language — try it:', link),
      subject: cfg.appName);
}

/// Share a saved notes PDF; the app link goes with it. Falls back to text if the PDF can't be downloaded.
Future<void> shareNote(BuildContext context, SavedNote note) async {
  final scope = AppScope.of(context);
  final link = await _link(context);
  final text = _withLink('My notes from ${scope.cfg.teacherName}’s class: ${note.title}\nGet the app:', link);
  try {
    final bytes = await scope.api.notePdf(note.id);
    final safe = note.title.replaceAll(RegExp(r'[^\wऀ-੿ -]'), '').trim();
    final name = '${safe.isEmpty ? 'notes' : safe.substring(0, min(safe.length, 40))}.pdf';
    await Share.shareXFiles([XFile.fromData(bytes, mimeType: 'application/pdf', name: name)],
        text: text, subject: note.title);
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
    await Share.share(text, subject: note.title);
  } catch (_) {
    if (context.mounted) _toast(context, 'Could not attach the PDF — sharing the link instead.');
    await Share.share(text, subject: note.title);
  }
}

/// Share a test score.
Future<void> shareTestResult(BuildContext context, TestResult r) async {
  final cfg = AppScope.of(context).cfg;
  final link = await _link(context);
  await Share.share(
      _withLink('I scored ${r.scoreText} (${r.percent}%) in ${cfg.teacherName}’s test! Study with the same AI teacher:', link),
      subject: cfg.appName);
}
