import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import 'live_screen.dart';

/// B1: where to go after login (and whenever the server says a step is missing).
Widget screenFor(Access a) {
  if (a.profileNeeded) return ClassScreen(options: a.classOptions);
  if (a.consentNeeded) return const ParentScreen();
  return const LiveScreen();
}

void goTo(BuildContext context, Access a) =>
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => screenFor(a)), (_) => false);

/// "Which class are you in?" + "Are you 18 or older?" — one screen, one button.
class ClassScreen extends StatefulWidget {
  final List<ClassOption> options;
  const ClassScreen({super.key, this.options = const []});
  @override
  State<ClassScreen> createState() => _ClassScreenState();
}

class _ClassScreenState extends State<ClassScreen> {
  String? _class;
  bool? _adult;
  bool _busy = false;
  String? _error;

  List<ClassOption> get _options => widget.options.isNotEmpty ? widget.options : ClassOption.defaults;

  Future<void> _continue() async {
    if (_class == null || _adult == null) {
      setState(() => _error = _class == null ? 'Choose your class' : 'Tell us if you are 18 or older');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final a = await AppScope.of(context).api.setProfile(_class!, _adult!);
      if (mounted) goTo(context, a);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _chip(String label, bool selected, VoidCallback onTap, Color accent) => ChoiceChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => onTap(),
        selectedColor: accent,
        labelStyle: TextStyle(fontWeight: FontWeight.w700, color: selected ? LT.onAccent : LT.text),
        backgroundColor: LT.surface,
        side: BorderSide(color: selected ? accent : LT.border),
        showCheckmark: false,
      );

  @override
  Widget build(BuildContext context) {
    final accent = AppScope.of(context).cfg.accent;
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.fromLTRB(22, 28, 22, 24), children: [
          const Text('Which class are you in?', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          const Text('Sir will explain everything at your level.', style: TextStyle(color: LT.muted, fontSize: 15)),
          const SizedBox(height: 18),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final o in _options) _chip(o.label, _class == o.value, () => setState(() => _class = o.value), accent),
          ]),
          const SizedBox(height: 28),
          const Text('Are you 18 or older?', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 10),
          Wrap(spacing: 8, children: [
            _chip('Yes, 18 or older', _adult == true, () => setState(() => _adult = true), accent),
            _chip('No, under 18', _adult == false, () => setState(() => _adult = false), accent),
          ]),
          if (_adult == false)
            const Padding(
              padding: EdgeInsets.only(top: 10),
              child: Text('Next, your mother or father will get a code by SMS to allow LiveTeach.',
                  style: TextStyle(color: LT.muted, fontSize: 13)),
            ),
          if (_error != null)
            Padding(padding: const EdgeInsets.only(top: 14), child: Text(_error!, style: const TextStyle(color: Color(0xFFFCA5A5)))),
          const SizedBox(height: 28),
          PrimaryButton(label: 'Continue', icon: Icons.arrow_forward_rounded, busy: _busy, onPressed: _continue),
        ]),
      ),
    );
  }
}

/// Under 18: a parent's phone → the parent gets a code → the student types it in.
class ParentScreen extends StatefulWidget {
  const ParentScreen({super.key});
  @override
  State<ParentScreen> createState() => _ParentScreenState();
}

class _ParentScreenState extends State<ParentScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  bool _sent = false;
  bool _busy = false;
  String? _error;
  int _seconds = 0;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    _phone.dispose();
    _code.dispose();
    super.dispose();
  }

  void _startTimer() {
    _timer?.cancel();
    _seconds = 30;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (_seconds == 0) {
        t.cancel();
      } else if (mounted) {
        setState(() => _seconds--);
      }
    });
  }

  Future<void> _run(Future<void> Function() job) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await job();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'No internet connection. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send() => _run(() async {
        if (_phone.text.length != 10) throw ApiException(0, 'Enter your parent’s 10-digit mobile number');
        await AppScope.of(context).api.sendParentOtp(_phone.text);
        setState(() => _sent = true);
        _startTimer();
      });

  Future<void> _verify() => _run(() async {
        if (_code.text.length != 6) throw ApiException(0, 'Enter the 6-digit code your parent received');
        final a = await AppScope.of(context).api.verifyParentOtp(_phone.text, _code.text);
        if (mounted) goTo(context, a);
      });

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.fromLTRB(22, 28, 22, 24), children: [
          const Text('Ask a parent to allow', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          const Text('You are under 18, so your mother or father needs to allow LiveTeach. We will send them a code by SMS.',
              style: TextStyle(color: LT.muted, fontSize: 15, height: 1.4)),
          const SizedBox(height: 20),
          TextField(
            controller: _phone,
            enabled: !_sent,
            keyboardType: TextInputType.phone,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(10)],
            decoration: const InputDecoration(labelText: 'Parent’s mobile number', prefixText: '+91  '),
          ),
          if (_sent) ...[
            const SizedBox(height: 14),
            TextField(
              controller: _code,
              autofocus: true,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
              decoration: const InputDecoration(labelText: 'Code your parent received'),
            ),
            if (api.isDemo)
              const Padding(padding: EdgeInsets.only(top: 6),
                  child: Text('Demo mode: any 6 digits will work', style: TextStyle(color: LT.accentText, fontSize: 13))),
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              TextButton(onPressed: _busy ? null : () => setState(() => _sent = false), child: const Text('Change number')),
              _seconds > 0
                  ? Text('Resend in 0:${_seconds.toString().padLeft(2, '0')}', style: const TextStyle(color: LT.muted, fontSize: 13))
                  : TextButton(onPressed: _busy ? null : _send, child: const Text('Resend code')),
            ]),
          ],
          if (_error != null)
            Padding(padding: const EdgeInsets.only(top: 10), child: Text(_error!, style: const TextStyle(color: Color(0xFFFCA5A5)))),
          const SizedBox(height: 24),
          _sent
              ? PrimaryButton(label: 'Allow & start class', icon: Icons.videocam_rounded, busy: _busy, onPressed: _verify)
              : PrimaryButton(label: 'Send code to parent', icon: Icons.sms_outlined, busy: _busy, onPressed: _send),
          const SizedBox(height: 8),
          Center(
            child: TextButton(
              onPressed: _busy ? null : () => Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const ClassScreen()), (_) => false),
              child: const Text('I chose the wrong class / age'),
            ),
          ),
        ]),
      ),
    );
  }
}
