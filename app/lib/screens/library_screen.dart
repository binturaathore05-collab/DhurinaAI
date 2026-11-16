import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../theme.dart';

/// Screen 4 · My Library: search, the Saved Notes box, and the full question history by day.
class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});
  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  Library? _lib;
  String _query = '';
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    try {
      final lib = await AppScope.of(context).api.library();
      if (mounted) setState(() => _lib = lib);
    } catch (_) {
      if (mounted) setState(() => _error = 'Could not load your library. Pull down to retry.');
    }
  }

  String _day(String createdAt) {
    final d = DateTime.tryParse(createdAt);
    if (d == null) return 'EARLIER';
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final that = DateTime(d.year, d.month, d.day);
    final diff = today.difference(that).inDays;
    if (diff == 0) return 'TODAY';
    if (diff == 1) return 'YESTERDAY';
    return '${d.day}/${d.month}/${d.year}';
  }

  void _openAnswer(HistoryItem h) {
    showModalBottomSheet(
      context: context,
      backgroundColor: LT.surface2,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        builder: (_, controller) => ListView(controller: controller, padding: const EdgeInsets.all(22), children: [
          Text(h.question, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 12),
          Text(h.answer, style: const TextStyle(fontSize: 16, height: 1.5)),
          if (h.needsReview) ...[
            const SizedBox(height: 12),
            const Text('General AI · awaiting Sir’s review', style: TextStyle(color: LT.muted, fontSize: 12)),
          ],
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final accent = AppScope.of(context).cfg.accent;
    final lib = _lib;
    final q = _query.toLowerCase();
    final notes = lib?.notes.where((n) => n.title.toLowerCase().contains(q)).toList() ?? [];
    final history = lib?.history
            .where((h) => h.question.toLowerCase().contains(q) || h.answer.toLowerCase().contains(q))
            .toList() ??
        [];
    final rows = <Widget>[];
    String? lastDay;
    for (final h in history) {
      final day = _day(h.createdAt);
      if (day != lastDay) {
        rows.add(Padding(
          padding: const EdgeInsets.only(top: 14, bottom: 2),
          child: Text(day, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
        ));
        lastDay = day;
      }
      rows.add(InkWell(
        onTap: () => _openAnswer(h),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFF1E293B)))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(h.question, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(h.answer, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13, color: LT.muted, height: 1.4)),
            if (h.pdfSaved)
              Container(
                margin: const EdgeInsets.only(top: 6),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: accent, borderRadius: BorderRadius.circular(999)),
                child: const Text('PDF saved', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: LT.onAccent)),
              ),
          ]),
        ),
      ));
    }

    return Scaffold(
      appBar: AppBar(
        backgroundColor: LT.bg,
        title: const Text('My Library', style: TextStyle(fontWeight: FontWeight.w800)),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
          TextField(
            onChanged: (v) => setState(() => _query = v),
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search, color: LT.muted), hintText: 'Search questions & notes', isDense: true),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: LT.surface2,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: accent, width: 1.5),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                const Text('Saved Notes', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                Text('${notes.length} PDFs', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: LT.accentText)),
              ]),
              const SizedBox(height: 12),
              if (notes.isEmpty)
                const Text('Notes you save during class appear here.', style: TextStyle(color: LT.muted, fontSize: 13))
              else
                GridView.count(
                  crossAxisCount: 2,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 10,
                  crossAxisSpacing: 10,
                  childAspectRatio: 1.25,
                  children: [
                    for (final n in notes)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: LT.surface,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: LT.border, width: 1.5),
                        ),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Container(
                            width: 34, height: 34,
                            decoration: BoxDecoration(color: const Color(0xFF3B1D1D), borderRadius: BorderRadius.circular(10)),
                            child: const Icon(Icons.picture_as_pdf_outlined, color: Color(0xFFFCA5A5), size: 18),
                          ),
                          const SizedBox(height: 8),
                          Expanded(
                            child: Text(n.title, maxLines: 2, overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, height: 1.3)),
                          ),
                          Text(_day(n.createdAt).toLowerCase(), style: const TextStyle(fontSize: 11, color: LT.muted)),
                        ]),
                      ),
                  ],
                ),
            ]),
          ),
          const SizedBox(height: 18),
          const Text('Question history', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: LT.muted))),
          if (lib != null && history.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 12),
              child: Text('Your questions to Sir will appear here.', style: TextStyle(color: LT.muted)),
            ),
          if (lib == null && _error == null) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
          ...rows,
        ]),
      ),
    );
  }
}
