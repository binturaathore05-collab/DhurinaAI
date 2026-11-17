import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../share.dart';
import '../theme.dart';
import 'pdf_screen.dart';

String dayLabel(String createdAt) {
  final d = DateTime.tryParse(createdAt);
  if (d == null) return 'EARLIER';
  final now = DateTime.now();
  final diff = DateTime(now.year, now.month, now.day).difference(DateTime(d.year, d.month, d.day)).inDays;
  if (diff == 0) return 'TODAY';
  if (diff == 1) return 'YESTERDAY';
  return '${d.day}/${d.month}/${d.year}';
}

/// Screen 4 · My Library. The Saved Notes box has a FIXED height: the latest notes scroll sideways
/// and "See all" opens the full list — so 5 notes or 5,000, this screen stays the same size.
/// Question history loads 30 at a time as the student scrolls.
class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});
  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final _scroll = ScrollController();
  Timer? _debounce;
  String _query = '';
  List<SavedNote> _notes = [];
  int _notesTotal = 0;
  final List<HistoryItem> _history = [];
  int _historyTotal = 0;
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 400) _loadMore();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _reload());
  }

  @override
  void dispose() {
    _scroll.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final lib = await AppScope.of(context).api.library(query: _query);
      if (!mounted) return;
      setState(() {
        _notes = lib.notes;
        _notesTotal = lib.notesTotal;
        _history
          ..clear()
          ..addAll(lib.history);
        _historyTotal = lib.historyTotal;
      });
    } catch (_) {
      if (mounted) setState(() => _error = 'Could not load your library. Pull down to retry.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    if (_loading || _loadingMore || _history.length >= _historyTotal) return;
    setState(() => _loadingMore = true);
    try {
      final lib = await AppScope.of(context).api.library(query: _query, historyOffset: _history.length);
      if (mounted) setState(() => _history.addAll(lib.history));
    } catch (_) {
      // keep what we have; the next scroll retries
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _onSearch(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      _query = v.trim();
      _reload();
    });
  }

  void _openAnswer(HistoryItem h) => showModalBottomSheet(
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

  void _openAllNotes() =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => AllNotesScreen(initialQuery: _query)));

  @override
  Widget build(BuildContext context) {
    final accent = AppScope.of(context).cfg.accent;
    // header widgets + one row per history item (+ day labels) + loader, built lazily
    final items = <Object>[];
    String? lastDay;
    for (final h in _history) {
      final day = dayLabel(h.createdAt);
      if (day != lastDay) {
        items.add(day);
        lastDay = day;
      }
      items.add(h);
    }

    return Scaffold(
      appBar: AppBar(backgroundColor: LT.bg, title: const Text('My Library', style: TextStyle(fontWeight: FontWeight.w800))),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: CustomScrollView(controller: _scroll, slivers: [
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            sliver: SliverList(
              delegate: SliverChildListDelegate([
                TextField(
                  onChanged: _onSearch,
                  decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search, color: LT.muted), hintText: 'Search questions & notes', isDense: true),
                ),
                const SizedBox(height: 14),
                _savedNotesBox(accent),
                const SizedBox(height: 18),
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  const Text('Question history', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                  if (_historyTotal > 0) Text('$_historyTotal', style: const TextStyle(color: LT.muted, fontSize: 12)),
                ]),
                if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: LT.muted))),
                if (_loading) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
                if (!_loading && _history.isEmpty && _error == null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(_query.isEmpty ? 'Your questions to Sir will appear here.' : 'Nothing found for “$_query”.',
                        style: const TextStyle(color: LT.muted)),
                  ),
              ]),
            ),
          ),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            sliver: SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, i) {
                  final item = items[i];
                  if (item is String) {
                    return Padding(
                      padding: const EdgeInsets.only(top: 14, bottom: 2),
                      child: Text(item, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1, color: LT.muted)),
                    );
                  }
                  return _historyRow(item as HistoryItem, accent);
                },
                childCount: items.length,
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: _loadingMore ? const Center(child: CircularProgressIndicator()) : const SizedBox.shrink(),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _savedNotesBox(Color accent) => Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
        decoration: BoxDecoration(
          color: LT.surface2,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: accent, width: 1.5),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Text('Saved Notes', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
            const SizedBox(width: 8),
            Text('$_notesTotal PDFs', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: LT.accentText)),
            const Spacer(),
            if (_notesTotal > 0) TextButton(onPressed: _openAllNotes, child: const Text('See all')),
          ]),
          const SizedBox(height: 6),
          if (_notes.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('Notes you save during class appear here.', style: TextStyle(color: LT.muted, fontSize: 13)),
            )
          else
            SizedBox(
              height: 120, // fixed: the box never grows, however many notes are saved
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _notes.length + (_notesTotal > _notes.length ? 1 : 0),
                separatorBuilder: (_, __) => const SizedBox(width: 10),
                itemBuilder: (_, i) => i < _notes.length
                    ? SizedBox(width: 150, child: NoteTile(note: _notes[i]))
                    : SizedBox(width: 110, child: _seeAllTile(accent)),
              ),
            ),
        ]),
      );

  Widget _seeAllTile(Color accent) => InkWell(
        onTap: _openAllNotes,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          decoration: BoxDecoration(color: LT.accentSoft, borderRadius: BorderRadius.circular(16), border: Border.all(color: accent)),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(Icons.arrow_forward_rounded, color: accent),
            const SizedBox(height: 6),
            Text('See all\n$_notesTotal', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700)),
          ]),
        ),
      );

  Widget _historyRow(HistoryItem h, Color accent) => InkWell(
        onTap: () => _openAnswer(h),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFF1E293B)))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(h.question, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
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
      );
}

class NoteTile extends StatelessWidget {
  final SavedNote note;
  const NoteTile({super.key, required this.note});

  @override
  Widget build(BuildContext context) => Material(
        color: LT.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          // tap the card → the PDF opens inside the app
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PdfScreen(note: note))),
          child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: LT.border, width: 1.5),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(color: const Color(0xFF3B1D1D), borderRadius: BorderRadius.circular(10)),
              child: const Icon(Icons.picture_as_pdf_outlined, color: Color(0xFFFCA5A5), size: 18),
            ),
            const Spacer(),
            IconButton(
              tooltip: 'Share',
              visualDensity: VisualDensity.compact,
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
              icon: const Icon(Icons.share_outlined, size: 18, color: LT.muted),
              onPressed: () => shareNote(context, note),
            ),
          ]),
          const SizedBox(height: 8),
          Expanded(
            child: Text(note.title, maxLines: 2, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, height: 1.3)),
          ),
          Text(
              note.kind == 'class'
                  ? 'class · ${note.topics.length} ${note.topics.length == 1 ? 'topic' : 'topics'} · ${dayLabel(note.createdAt).toLowerCase()}'
                  : dayLabel(note.createdAt).toLowerCase(),
              maxLines: 1, overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: LT.muted)),
        ]),
          ),
        ),
      );
}

/// All saved notes: searchable grid that loads 20 at a time as you scroll.
class AllNotesScreen extends StatefulWidget {
  final String initialQuery;
  const AllNotesScreen({super.key, this.initialQuery = ''});
  @override
  State<AllNotesScreen> createState() => _AllNotesScreenState();
}

class _AllNotesScreenState extends State<AllNotesScreen> {
  final _scroll = ScrollController();
  final List<SavedNote> _items = [];
  Timer? _debounce;
  late String _query = widget.initialQuery;
  int _total = 0;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 400) _load();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _load(reset: true));
  }

  @override
  void dispose() {
    _scroll.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _load({bool reset = false}) async {
    if (_loading || (!reset && _items.length >= _total)) return;
    setState(() => _loading = true);
    try {
      final page = await AppScope.of(context).api.notes(offset: reset ? 0 : _items.length, query: _query);
      if (!mounted) return;
      setState(() {
        if (reset) _items.clear();
        _items.addAll(page.items);
        _total = page.total;
      });
    } catch (_) {
      // pull to refresh retries
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(backgroundColor: LT.bg, title: Text('Saved Notes ($_total)', style: const TextStyle(fontWeight: FontWeight.w800))),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
          child: TextFormField(
            initialValue: _query,
            onChanged: (v) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 350), () {
                _query = v.trim();
                _load(reset: true);
              });
            },
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search, color: LT.muted), hintText: 'Search notes', isDense: true),
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => _load(reset: true),
            child: GridView.builder(
              controller: _scroll,
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2, mainAxisSpacing: 10, crossAxisSpacing: 10, childAspectRatio: 1.25),
              itemCount: _items.length,
              itemBuilder: (_, i) => NoteTile(note: _items[i]),
            ),
          ),
        ),
        if (_loading) const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()),
      ]),
    );
  }
}
