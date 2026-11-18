import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';
import '../voice.dart';
import 'delete_data.dart';
import 'login_screen.dart';
import 'pay_screen.dart';

/// "open my profile" said or typed to Sir (same list as the server: backend/app/services/tutor.py PROFILE_PHRASES).
const _profilePhrases = [
  'my profile', 'open profile', 'profile kholo', 'profile khol do', 'profile dikhao', 'mera profile', 'logout',
  'log out', 'number change', 'number badalna', 'number badlo', 'mera number badlo', 'mera naam badlo',
  'मेरा प्रोफाइल', 'प्रोफाइल खोलो', 'प्रोफाइल दिखाओ', 'लॉग आउट', 'नंबर बदलो', 'मेरा नंबर बदलो', 'मेरा नाम बदलो',
  'ਮੇਰਾ ਪ੍ਰੋਫਾਈਲ', 'ਪ੍ਰੋਫਾਈਲ ਖੋਲ੍ਹੋ', 'ਲੌਗ ਆਊਟ', 'ਨੰਬਰ ਬਦਲੋ',
];

bool isProfileCommand(String text) {
  final low = ' ${text.toLowerCase().replaceAll(RegExp(r'[^\wऀ-੿]+'), ' ').trim()} ';
  return _profilePhrases.any((p) => low.contains(' $p '));
}

void openProfile(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProfileScreen()));

/// The student's own account: name, number, class, plan; change number, log out, delete account.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Me? _me;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_me == null && _error == null) _load();
  }

  Future<void> _load() async {
    try {
      final m = await AppScope.of(context).api.me();
      if (mounted) setState(() => _me = m);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'No internet connection. Please try again.');
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _phoneText(String p) {
    final d = p.replaceAll(RegExp(r'\D'), '');
    final ten = d.length > 10 ? d.substring(d.length - 10) : d;
    return ten.length == 10 ? '+91 ${ten.substring(0, 5)} ${ten.substring(5)}' : p;
  }

  String _planText(Me m) {
    final a = m.access;
    switch (a.state) {
      case 'active':
        final days = a.daysLeft ?? 0;
        return '${m.freePlan ? 'Free plan' : 'Plan active'} · ${days <= 0 ? 'ends today' : '$days days left'}';
      case 'grace':
        return 'Plan ended · ${a.graceLeft} questions left';
      case 'expired':
        return 'Plan ended';
      default:
        return 'Free demo · ${a.demoLeft} questions left';
    }
  }

  Future<void> _editName() async {
    final ctrl = TextEditingController(text: _me?.name ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: LT.surface,
        title: const Text('What should Sir call you?'),
        content: TextField(controller: ctrl, autofocus: true, maxLength: 40,
            textCapitalization: TextCapitalization.words, decoration: const InputDecoration(hintText: 'Your name')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, ctrl.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    if (name == null || !mounted) return;
    try {
      await AppScope.of(context).api.setName(name);
      _toast('Saved');
      _load();
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  /// Two steps in one sheet: the new number → the code sent to it.
  Future<void> _changeNumber() async {
    final api = AppScope.of(context).api;
    final phoneCtrl = TextEditingController();
    final codeCtrl = TextEditingController();
    var codeSent = false, busy = false;
    String? err;
    final done = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: LT.surface2,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) {
          Future<void> go() async {
            set(() {
              busy = true;
              err = null;
            });
            try {
              if (!codeSent) {
                await api.changePhoneOtp(phoneCtrl.text);
                set(() => codeSent = true);
              } else {
                final p = await api.changePhoneVerify(phoneCtrl.text, codeCtrl.text);
                if (ctx.mounted) Navigator.pop(ctx, p);
              }
            } on ApiException catch (e) {
              set(() => err = e.message);
            } catch (_) {
              set(() => err = 'No internet connection. Please try again.');
            } finally {
              if (ctx.mounted) set(() => busy = false);
            }
          }

          return Padding(
            padding: EdgeInsets.fromLTRB(20, 18, 20, 20 + MediaQuery.of(ctx).viewInsets.bottom),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Change mobile number', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(codeSent
                  ? 'Enter the 6-digit code sent to ${phoneCtrl.text}.'
                  : 'Your classes, notes, tests and plan stay with you. We send a code to the new number.',
                  style: const TextStyle(color: LT.muted, height: 1.4)),
              const SizedBox(height: 14),
              TextField(
                controller: phoneCtrl,
                enabled: !codeSent,
                keyboardType: TextInputType.phone,
                maxLength: 10,
                decoration: const InputDecoration(labelText: 'New mobile number', prefixText: '+91 ', counterText: ''),
              ),
              if (codeSent) ...[
                const SizedBox(height: 10),
                TextField(controller: codeCtrl, autofocus: true, keyboardType: TextInputType.number, maxLength: 6,
                    decoration: const InputDecoration(labelText: '6-digit code', counterText: '')),
              ],
              if (err != null) Padding(padding: const EdgeInsets.only(top: 8),
                  child: Text(err!, style: const TextStyle(color: LT.danger))),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                height: 52,
                child: FilledButton(
                  onPressed: busy ? null : go,
                  child: Text(busy ? 'Please wait…' : codeSent ? 'Confirm new number' : 'Send code',
                      style: const TextStyle(fontWeight: FontWeight.w800)),
                ),
              ),
            ]),
          );
        },
      ),
    );
    if (done != null && mounted) {
      _toast('Your number is now ${_phoneText(done)}');
      _load();
    }
  }

  /// S3: e.g. an old phone was lost or someone else knows the login — every other phone is logged out.
  Future<void> _logoutOthers() async {
    final ok = await confirmAction(context,
        title: 'Log out on other phones?',
        message: 'Every other phone with your account is logged out at once. This phone stays logged in.',
        confirmLabel: 'Log out others');
    if (!ok || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await AppScope.of(context).api.logoutOthers();
      messenger.showSnackBar(const SnackBar(content: Text('Done — only this phone is logged in now')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _logout() async {
    final ok = await confirmAction(context,
        title: 'Log out?', message: 'Your classes, notes and plan stay saved. Log in again with your number any time.',
        confirmLabel: 'Log out');
    if (!ok || !mounted) return;
    await Voice.instance.stopSpeaking();
    if (!mounted) return;
    await AppScope.of(context).api.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    final accent = AppScope.of(context).cfg.accent;
    final m = _me;
    return Scaffold(
      appBar: AppBar(backgroundColor: LT.bg, title: const Text('Profile', style: TextStyle(fontWeight: FontWeight.w800))),
      body: SafeArea(
        child: m == null
            ? Center(child: _error == null
                ? const CircularProgressIndicator()
                : Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
            : RefreshIndicator(
                onRefresh: _load,
                child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
                  // who
                  Row(children: [
                    CircleAvatar(radius: 32, backgroundColor: accent,
                        child: Text(m.name.isEmpty ? '?' : m.name.characters.first.toUpperCase(),
                            style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: LT.onAccent))),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(m.name.isEmpty ? 'Add your name' : m.name,
                            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: m.name.isEmpty ? LT.muted : LT.text)),
                        const SizedBox(height: 2),
                        Text(_phoneText(m.phone), style: const TextStyle(color: LT.muted)),
                      ]),
                    ),
                    IconButton(tooltip: 'Edit name', onPressed: _editName, icon: const Icon(Icons.edit_outlined)),
                  ]),
                  const SizedBox(height: 18),
                  // plan
                  _card(children: [
                    _row(Icons.workspace_premium_outlined, 'Plan', _planText(m)),
                    if (m.access.state != 'active' || (m.access.renewSoon && !m.freePlan))
                      Padding(
                        padding: const EdgeInsets.only(top: 10),
                        child: SizedBox(width: double.infinity, height: 48, child: FilledButton(
                          onPressed: () => Navigator.of(context)
                              .push(MaterialPageRoute(builder: (_) => PayScreen(access: m.access)))
                              .then((_) => _load()),
                          child: Text(m.access.state == 'active' ? 'Renew plan' : 'See plans',
                              style: const TextStyle(fontWeight: FontWeight.w800)),
                        )),
                      ),
                  ]),
                  const SizedBox(height: 12),
                  _card(children: [
                    _row(Icons.school_outlined, 'Class', m.classLevel == null ? 'Not given'
                        : m.classLevel == 'college' ? 'College / exam preparation' : 'Class ${m.classLevel}'),
                    if (m.consent != 'not_needed') ...[
                      const Divider(color: LT.border, height: 20),
                      _row(Icons.family_restroom_outlined, 'Parent’s permission',
                          m.consent == 'given' ? 'Given' : m.consent == 'withdrawn' ? 'Withdrawn' : 'Still needed'),
                    ],
                  ]),
                  const SizedBox(height: 12),
                  _card(children: [
                    _tile(Icons.phone_iphone_rounded, 'Change mobile number', _changeNumber),
                    const Divider(color: LT.border, height: 1),
                    _tile(Icons.devices_other_rounded, 'Log out on other phones', _logoutOthers),
                    const Divider(color: LT.border, height: 1),
                    _tile(Icons.logout_rounded, 'Log out', _logout),
                  ]),
                  const SizedBox(height: 12),
                  _card(children: [
                    _tile(Icons.delete_forever_outlined, 'Delete my account & data', () => confirmDeleteMyData(context),
                        color: LT.danger),
                  ]),
                ]),
              ),
      ),
    );
  }

  Widget _card({required List<Widget> children}) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: LT.surface, borderRadius: BorderRadius.circular(18),
            border: Border.all(color: LT.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
      );

  Widget _row(IconData icon, String label, String value) => Row(children: [
        Icon(icon, color: LT.accentText, size: 22),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: LT.muted, fontSize: 12)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        ])),
      ]);

  Widget _tile(IconData icon, String label, VoidCallback onTap, {Color color = LT.text}) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: SizedBox(
          height: 52,
          child: Row(children: [
            Icon(icon, color: color, size: 22),
            const SizedBox(width: 12),
            Expanded(child: Text(label, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: color))),
            Icon(Icons.chevron_right_rounded, color: color == LT.text ? LT.muted : color),
          ]),
        ),
      );
}
