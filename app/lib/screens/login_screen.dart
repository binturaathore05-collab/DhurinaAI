import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import 'otp_screen.dart';

/// Screen 1 · Login: teacher photo, headline, mobile number, "Start free demo call".
class LoginScreen extends StatefulWidget {
  /// Shown once on top, e.g. "Your login has ended. Please log in again."
  final String? notice;
  const LoginScreen({super.key, this.notice});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  bool _busy = false;
  bool _slow = false; // the server is waking up: say so instead of looking stuck
  late String? _error = widget.notice;
  Timer? _slowTimer;

  @override
  void initState() {
    super.initState();
    // wake the server while the student types the number
    WidgetsBinding.instance.addPostFrameCallback((_) => AppScope.of(context).api.warmUp());
  }

  @override
  void dispose() {
    _slowTimer?.cancel();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final digits = _phone.text.replaceAll(RegExp(r'\D'), '');
    if (digits.length != 10) {
      setState(() => _error = 'Enter your 10-digit mobile number');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    _slowTimer = Timer(const Duration(seconds: 4), () {
      if (mounted && _busy) setState(() => _slow = true);
    });
    try {
      await AppScope.of(context).api.sendOtp(digits);
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => OtpScreen(phone: digits)));
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'No internet connection. Please try again.');
    } finally {
      _slowTimer?.cancel();
      if (mounted) {
        setState(() {
          _busy = false;
          _slow = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final cfg = scope.cfg;
    return Scaffold(
      body: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ClipRRect(
              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
              child: SizedBox(
                height: MediaQuery.of(context).size.height * 0.5,
                child: Image.asset(cfg.avatar, fit: BoxFit.cover, alignment: const Alignment(0, -0.6)),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Container(width: 8, height: 8, decoration: BoxDecoration(color: cfg.accent, shape: BoxShape.circle)),
                    const SizedBox(width: 8),
                    Text('${cfg.teacherName} is available now',
                        style: const TextStyle(color: LT.accentText, fontWeight: FontWeight.w600, fontSize: 13)),
                  ]),
                  const SizedBox(height: 12),
                  const Text('Call your AI teacher, anytime.',
                      style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, height: 1.15)),
                  const SizedBox(height: 8),
                  const Text('Ask any doubt. Sir explains, then checks if you understood.',
                      style: TextStyle(fontSize: 15, color: LT.muted, height: 1.5)),
                  const SizedBox(height: 24),
                  const Text('Mobile number', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(10)],
                    style: const TextStyle(fontSize: 17),
                    decoration: InputDecoration(
                      hintText: '98765 43210',
                      prefixIcon: const Padding(
                        padding: EdgeInsets.only(left: 14, right: 8),
                        child: Text('+91', style: TextStyle(fontSize: 16, color: LT.muted, fontWeight: FontWeight.w600)),
                      ),
                      prefixIconConstraints: const BoxConstraints(minWidth: 0, minHeight: 0),
                      errorText: _error,
                    ),
                    onSubmitted: (_) => _start(),
                  ),
                  const SizedBox(height: 12),
                  PrimaryButton(label: 'Start free demo call', icon: Icons.videocam_rounded, busy: _busy, onPressed: _start),
                  if (_slow)
                    const Padding(
                      padding: EdgeInsets.only(top: 8),
                      child: Center(
                        child: Text('Connecting to Sir… this can take up to a minute the first time.',
                            textAlign: TextAlign.center, style: TextStyle(color: LT.accentText, fontSize: 13)),
                      ),
                    ),
                  const SizedBox(height: 10),
                  Center(
                    child: Text(
                      '3 free questions · LiveTeach',
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 12, color: LT.muted),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
