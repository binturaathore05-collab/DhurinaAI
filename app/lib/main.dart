import 'package:flutter/material.dart';

import 'api.dart';
import 'config.dart';
import 'screens/live_screen.dart';
import 'screens/login_screen.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final cfg = await TeacherConfig.load();
  final api = Api.create(cfg);
  final loggedIn = await api.hasSession();
  runApp(LiveTeachApp(cfg: cfg, api: api, loggedIn: loggedIn));
}

/// Gives every screen the teacher config and the API client.
class AppScope extends InheritedWidget {
  final TeacherConfig cfg;
  final Api api;
  const AppScope({super.key, required this.cfg, required this.api, required super.child});

  static AppScope of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!;

  @override
  bool updateShouldNotify(AppScope oldWidget) => false;
}

class LiveTeachApp extends StatelessWidget {
  final TeacherConfig cfg;
  final Api api;
  final bool loggedIn;
  const LiveTeachApp({super.key, required this.cfg, required this.api, required this.loggedIn});

  @override
  Widget build(BuildContext context) {
    return AppScope(
      cfg: cfg,
      api: api,
      child: MaterialApp(
        title: cfg.appName,
        debugShowCheckedModeBanner: false,
        theme: buildTheme(cfg.accent),
        home: loggedIn ? const LiveScreen() : const LoginScreen(),
      ),
    );
  }
}
