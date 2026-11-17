import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import 'login_screen.dart';

/// B6: same phrases as the server (backend/app/services/tutor.py DELETE_PHRASES) — saying it to Sir opens the
/// confirmation below; nothing is deleted without typing DELETE.
const _deletePhrases = [
  'delete my data', 'delete my account', 'remove my data', 'erase my data', 'mera data delete', 'mera account delete',
  'account delete kar', 'data delete kar', 'मेरा डेटा डिलीट', 'मेरा अकाउंट डिलीट', 'अकाउंट डिलीट कर', 'डेटा मिटा दो',
  'ਮੇਰਾ ਡਾਟਾ ਡਿਲੀਟ', 'ਮੇਰਾ ਅਕਾਊਂਟ ਡਿਲੀਟ',
];

bool isDeleteCommand(String text) {
  final low = ' ${text.toLowerCase().replaceAll(RegExp(r'[^\w\u0900-\u0A7F]+'), ' ').trim()} ';   // same as the other commands
  return _deletePhrases.any((p) => low.contains(' $p '));
}

/// Asks to confirm (type DELETE), then deletes and goes back to the login screen.
Future<void> confirmDeleteMyData(BuildContext context) async {
  final ctrl = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setD) => AlertDialog(
        backgroundColor: LT.surface,
        title: const Text('Delete my account and data?'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text(
              'This deletes your questions, Sir’s answers, your notes and tests, your name and class, and closes your '
              'account. It can’t be undone.\n\nPayment and safety records are kept as the law requires, without your '
              'phone number.',
              style: TextStyle(color: LT.muted, height: 1.4)),
          const SizedBox(height: 14),
          TextField(
            controller: ctrl,
            onChanged: (_) => setD(() {}),
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(labelText: 'Type DELETE to confirm'),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep my account')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: LT.danger),
            onPressed: ctrl.text.trim().toUpperCase() == 'DELETE' ? () => Navigator.pop(ctx, true) : null,
            child: const Text('Delete everything'),
          ),
        ],
      ),
    ),
  );
  if (ok != true || !context.mounted) return;
  try {
    await AppScope.of(context).api.deleteMyData();
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Your account and data were deleted.')));
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No internet connection. Please try again.')));
    }
  }
}
