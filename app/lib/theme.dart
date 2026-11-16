import 'package:flutter/material.dart';

/// Colours from the final "Video Call" design.
class LT {
  static const bg = Color(0xFF0B1220);
  static const surface = Color(0xFF162033);
  static const surface2 = Color(0xFF111A2B);
  static const border = Color(0xFF273449);
  static const text = Color(0xFFF1F5F9);
  static const muted = Color(0xFF94A3B8);
  static const onAccent = Color(0xFF04201C);
  static const danger = Color(0xFFDC2626);
  static const accentSoft = Color(0xFF0F2A2A);
  static const accentText = Color(0xFF5EEAD4);
}

ThemeData buildTheme(Color accent) {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: LT.bg,
    colorScheme: base.colorScheme.copyWith(primary: accent, surface: LT.bg, onPrimary: LT.onAccent),
    textTheme: base.textTheme.apply(bodyColor: LT.text, displayColor: LT.text),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: LT.surface,
      hintStyle: const TextStyle(color: LT.muted),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: LT.border)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: LT.border, width: 1.5)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: accent, width: 2)),
    ),
  );
}

/// Big rounded accent button used on every screen.
class PrimaryButton extends StatelessWidget {
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final bool busy;
  const PrimaryButton({super.key, required this.label, this.icon, this.onPressed, this.busy = false});

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: LT.onAccent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
        ),
        onPressed: busy ? null : onPressed,
        child: busy
            ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: LT.onAccent))
            : Row(mainAxisSize: MainAxisSize.min, children: [
                if (icon != null) ...[Icon(icon, size: 20), const SizedBox(width: 10)],
                Text(label),
              ]),
      ),
    );
  }
}

class RoundIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  final Color? background;
  final Color? foreground;
  final double size;
  const RoundIconButton({super.key, required this.icon, required this.tooltip, required this.onPressed,
      this.background, this.foreground, this.size = 56});

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: background ?? const Color(0xFF1E293B),
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onPressed,
          child: SizedBox(width: size, height: size, child: Icon(icon, color: foreground ?? LT.text, size: size * 0.42)),
        ),
      ),
    );
  }
}
