import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:printing/printing.dart';

import '../api.dart';
import '../main.dart';
import '../share.dart';
import '../theme.dart';

/// Opens a saved notes PDF inside the app: pinch to zoom, scroll through pages, Share in the top bar.
class PdfScreen extends StatefulWidget {
  final SavedNote note;
  const PdfScreen({super.key, required this.note});

  @override
  State<PdfScreen> createState() => _PdfScreenState();
}

class _PdfScreenState extends State<PdfScreen> {
  Future<Uint8List>? _pdf;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _pdf ??= AppScope.of(context).api.notePdf(widget.note.id);
  }

  void _retry() => setState(() => _pdf = AppScope.of(context).api.notePdf(widget.note.id));

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          backgroundColor: LT.bg,
          title: Text(widget.note.title, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          actions: [
            IconButton(
              tooltip: 'Share',
              icon: const Icon(Icons.share_outlined),
              onPressed: () => shareNote(context, widget.note),
            ),
          ],
        ),
        body: FutureBuilder<Uint8List>(
          future: _pdf,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError || snap.data == null) {
              final e = snap.error;
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(e is ApiException ? e.message : 'Could not open the PDF. Check your internet and try again.',
                        textAlign: TextAlign.center, style: const TextStyle(color: LT.muted)),
                    const SizedBox(height: 12),
                    FilledButton(onPressed: _retry, child: const Text('Try again')),
                  ]),
                ),
              );
            }
            final bytes = snap.data!;
            return PdfPreview(
              build: (_) async => bytes,
              useActions: false, // our own Share button is in the top bar (it adds the app link)
              allowPrinting: false,
              allowSharing: false,
              canChangePageFormat: false,
              canChangeOrientation: false,
              canDebug: false,
              pdfFileName: '${widget.note.title}.pdf',
              scrollViewDecoration: const BoxDecoration(color: LT.bg),
              loadingWidget: const Center(child: CircularProgressIndicator()),
            );
          },
        ),
      );
}
