import 'package:flutter/material.dart';
import 'package:razorpay_flutter/razorpay_flutter.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import 'success_screen.dart';

/// Screen 5 · Pay Now: plans, what's included, one "Pay Now" button that opens Razorpay.
/// Pops with `true` when the student has paid.
class PayScreen extends StatefulWidget {
  const PayScreen({super.key});
  @override
  State<PayScreen> createState() => _PayScreenState();
}

class _PayScreenState extends State<PayScreen> {
  List<Plan>? _plans;
  String? _selected;
  bool _busy = false;
  Razorpay? _razorpay;
  Checkout? _pending;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _razorpay?.clear();
    super.dispose();
  }

  Future<void> _load() async {
    final plans = await AppScope.of(context).api.plans();
    if (!mounted) return;
    setState(() {
      _plans = plans;
      _selected = plans.isNotEmpty ? plans.last.id : null; // longest plan pre-selected
    });
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _payNow() async {
    if (_selected == null) return;
    final api = AppScope.of(context).api;
    final cfg = AppScope.of(context).cfg;
    setState(() => _busy = true);
    try {
      final co = await api.checkout(_selected!);
      if (api.isDemo) {
        final receipt = await api.confirmPayment(co.orderId, 'pay_demo', 'demo');
        _finish(receipt);
        return;
      }
      _pending = co;
      _razorpay ??= Razorpay()
        ..on(Razorpay.EVENT_PAYMENT_SUCCESS, _onSuccess)
        ..on(Razorpay.EVENT_PAYMENT_ERROR, _onError);
      _razorpay!.open({
        'key': co.keyId,
        'order_id': co.orderId,
        'amount': co.amount,
        'currency': 'INR',
        'name': cfg.appName,
        'description': '${co.planName} plan',
      });
    } on ApiException catch (e) {
      _toast(e.message);
      setState(() => _busy = false);
    } catch (_) {
      _toast('Could not start payment. Please try again.');
      setState(() => _busy = false);
    }
  }

  Future<void> _onSuccess(PaymentSuccessResponse r) async {
    try {
      final receipt = await AppScope.of(context)
          .api
          .confirmPayment(r.orderId ?? _pending!.orderId, r.paymentId ?? '', r.signature ?? '');
      _finish(receipt);
    } catch (_) {
      _toast('Payment received. Activating your plan — please reopen the app in a minute.');
      setState(() => _busy = false);
    }
  }

  void _onError(PaymentFailureResponse r) {
    _toast(r.message ?? 'Payment was not completed.');
    setState(() => _busy = false);
  }

  void _finish(Receipt receipt) {
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => SuccessScreen(receipt: receipt)), result: true);
  }

  @override
  Widget build(BuildContext context) {
    final cfg = AppScope.of(context).cfg;
    final accent = cfg.accent;
    final plans = _plans;
    return Scaffold(
      body: Column(children: [
        SizedBox(
          height: 210,
          width: double.infinity,
          child: Stack(fit: StackFit.expand, children: [
            Opacity(opacity: 0.45, child: Image.asset(cfg.avatar, fit: BoxFit.cover, alignment: const Alignment(0, -0.6))),
            SafeArea(
              child: Align(
                alignment: Alignment.topLeft,
                child: IconButton(icon: const Icon(Icons.close), tooltip: 'Close', onPressed: () => Navigator.of(context).pop(false)),
              ),
            ),
          ]),
        ),
        Expanded(
          child: Container(
            width: double.infinity,
            decoration: const BoxDecoration(color: LT.surface2, borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
            transform: Matrix4.translationValues(0, -28, 0),
            child: ListView(padding: const EdgeInsets.fromLTRB(22, 26, 22, 24), children: [
              const Text('Your demo call has ended', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text('Continue learning with ${cfg.teacherName} — no limits.', style: const TextStyle(color: LT.muted)),
              const SizedBox(height: 16),
              for (final f in const [
                'Unlimited questions — voice, text or photo',
                'Sir’s own voice and video avatar',
                'Save any answer as PDF notes',
              ])
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(children: [
                    Icon(Icons.check, color: accent, size: 18),
                    const SizedBox(width: 10),
                    Expanded(child: Text(f, style: const TextStyle(fontSize: 14))),
                  ]),
                ),
              const SizedBox(height: 10),
              if (plans == null) const Center(child: CircularProgressIndicator()),
              if (plans != null)
                for (final p in plans)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () => setState(() => _selected = p.id),
                      child: Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: _selected == p.id ? LT.accentSoft : Colors.transparent,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: _selected == p.id ? accent : LT.border, width: 2),
                        ),
                        child: Row(children: [
                          Icon(_selected == p.id ? Icons.radio_button_checked : Icons.radio_button_off,
                              color: _selected == p.id ? accent : LT.muted),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(p.name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                              Text('${p.durationDays} days', style: const TextStyle(fontSize: 12, color: LT.muted)),
                            ]),
                          ),
                          Text(p.price, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                        ]),
                      ),
                    ),
                  ),
              const SizedBox(height: 8),
              PrimaryButton(label: 'Pay Now', busy: _busy, onPressed: _selected == null ? null : _payNow),
              const SizedBox(height: 10),
              const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(Icons.lock_outline, size: 14, color: LT.muted),
                SizedBox(width: 6),
                Text('Secure payment · Cancel anytime', style: TextStyle(fontSize: 12, color: LT.muted)),
              ]),
            ]),
          ),
        ),
      ]),
    );
  }
}
