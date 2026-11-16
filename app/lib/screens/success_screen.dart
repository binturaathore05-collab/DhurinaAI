import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';

/// Screen 6 · Payment successful: receipt and what is now unlocked. "Start learning" returns to class.
class SuccessScreen extends StatelessWidget {
  final Receipt receipt;
  const SuccessScreen({super.key, required this.receipt});

  @override
  Widget build(BuildContext context) {
    final cfg = AppScope.of(context).cfg;
    final accent = cfg.accent;
    final v = receipt.validTill;
    Widget row(String k, String val) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(k, style: const TextStyle(color: LT.muted)),
            Flexible(child: Text(val, textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w700))),
          ]),
        );
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.fromLTRB(22, 40, 22, 24), children: [
          Center(
            child: Stack(clipBehavior: Clip.none, children: [
              CircleAvatar(radius: 66, backgroundColor: accent, child: CircleAvatar(radius: 62, backgroundImage: AssetImage(cfg.avatar))),
              Positioned(
                right: -2,
                bottom: -2,
                child: Container(
                  width: 44, height: 44,
                  decoration: BoxDecoration(color: accent, shape: BoxShape.circle, border: Border.all(color: LT.bg, width: 4)),
                  child: const Icon(Icons.check, color: LT.onAccent, size: 24),
                ),
              ),
            ]),
          ),
          const SizedBox(height: 20),
          const Text('Payment successful!', textAlign: TextAlign.center, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text('Welcome to ${cfg.teacherName}’s class. Your plan is now active.',
              textAlign: TextAlign.center, style: const TextStyle(color: LT.muted, fontSize: 15)),
          const SizedBox(height: 20),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: LT.surface2, borderRadius: BorderRadius.circular(20), border: Border.all(color: LT.border, width: 1.5)),
            child: Column(children: [
              row('Plan', receipt.plan),
              row('Amount paid', receipt.amountPaise > 0 ? '₹${(receipt.amountPaise / 100).toStringAsFixed(0)}' : '—'),
              row('Valid till', '${v.day}/${v.month}/${v.year}'),
              row('Payment ID', receipt.paymentId),
            ]),
          ),
          const SizedBox(height: 18),
          const Text('NOW UNLOCKED', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
          const SizedBox(height: 8),
          for (final f in const [
            'Unlimited questions — voice, text or photo',
            'Save any answer as PDF notes',
            'Weekly progress report for parents',
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(children: [Icon(Icons.check, color: accent, size: 18), const SizedBox(width: 10), Expanded(child: Text(f))]),
            ),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Start learning', onPressed: () => Navigator.of(context).pop(true)),
        ]),
      ),
    );
  }
}
