import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import 'setup_screen.dart';

/// Screen 2 · OTP verification: six boxes (one hidden field), resend timer, "Verify & join class".
class OtpScreen extends StatefulWidget {
  final String phone;
  const OtpScreen({super.key, required this.phone});
  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final _code = TextEditingController();
  final _focus = FocusNode();
  Timer? _timer;
  int _seconds = 30;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _startTimer();
    _code.addListener(() {
      setState(() {});
      if (_code.text.length == 6) _verify();
    });
  }

  void _startTimer() {
    _timer?.cancel();
    _seconds = 30;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (_seconds == 0) {
        t.cancel();
      } else {
        setState(() => _seconds--);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _resend() async {
    setState(() => _error = null);
    try {
      await AppScope.of(context).api.sendOtp(widget.phone);
      _startTimer();
    } on ApiException catch (e) {
      setState(() => _error = e.message); // e.g. "Too many code requests. Please try again in 10 minutes."
    } catch (_) {
      setState(() => _error = 'No internet connection. Please try again.');
    }
  }

  Future<void> _verify() async {
    if (_busy || _code.text.length != 6) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final a = await AppScope.of(context).api.verifyOtp(widget.phone, _code.text);
      if (!mounted) return;
      goTo(context, a); // B1: class / parent's OK first if still needed, else straight to the class
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final accent = scope.cfg.accent;
    final digits = _code.text.split('');
    return Scaffold(
      appBar: AppBar(backgroundColor: LT.bg, elevation: 0),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 0, 22, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(radius: 38, backgroundColor: accent, child: CircleAvatar(radius: 35, backgroundImage: AssetImage(scope.cfg.avatar))),
              const SizedBox(height: 16),
              const Text('Verify your number', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text.rich(TextSpan(style: const TextStyle(fontSize: 15, color: LT.muted, height: 1.5), children: [
                const TextSpan(text: 'Enter the 6-digit code sent to '),
                TextSpan(text: '+91 ${widget.phone}', style: const TextStyle(color: LT.text, fontWeight: FontWeight.w700)),
              ])),
              if (scope.api.isDemo)
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text('Demo mode: any 6 digits will work', style: TextStyle(color: LT.accentText, fontSize: 13)),
                ),
              const SizedBox(height: 20),
              GestureDetector(
                onTap: () => _focus.requestFocus(),
                child: Stack(children: [
                  Row(
                    children: List.generate(6, (i) {
                      final filled = i < digits.length;
                      final active = i == digits.length;
                      return Expanded(
                        child: Container(
                          margin: EdgeInsets.only(right: i < 5 ? 8 : 0),
                          height: 58,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: LT.surface,
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: active ? accent : (filled ? const Color(0xFF3B4A63) : LT.border), width: 2),
                          ),
                          child: Text(filled ? digits[i] : '', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                        ),
                      );
                    }),
                  ),
                  // The real input is invisible; it receives the keyboard and SMS autofill.
                  Opacity(
                    opacity: 0,
                    child: SizedBox(
                      height: 58,
                      child: TextField(
                        controller: _code,
                        focusNode: _focus,
                        autofocus: true,
                        keyboardType: TextInputType.number,
                        autofillHints: const [AutofillHints.oneTimeCode],
                        inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
                      ),
                    ),
                  ),
                ]),
              ),
              const SizedBox(height: 12),
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                Text(_error ?? 'Reading OTP from SMS…',
                    style: TextStyle(color: _error != null ? const Color(0xFFFCA5A5) : LT.accentText, fontSize: 13)),
                _seconds > 0
                    ? Text('Resend in 0:${_seconds.toString().padLeft(2, '0')}', style: const TextStyle(color: LT.muted, fontSize: 13))
                    : TextButton(onPressed: _resend, child: const Text('Resend code')),
              ]),
              const Spacer(),
              PrimaryButton(label: 'Verify & join class', icon: Icons.videocam_rounded, busy: _busy, onPressed: _verify),
              const SizedBox(height: 10),
              const Center(
                child: Text('By continuing you agree to the Terms & Privacy Policy',
                    style: TextStyle(fontSize: 12, color: LT.muted)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
