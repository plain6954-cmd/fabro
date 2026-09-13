import 'package:flutter/material.dart';

/// Keep the current results visible while fetching or retrying another page.
class PaginationFooter extends StatelessWidget {
  const PaginationFooter({
    super.key,
    required this.loading,
    required this.hasMore,
    required this.onLoadMore,
    this.error,
  });

  final bool loading;
  final bool hasMore;
  final String? error;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    if (!loading && !hasMore) return const SizedBox.shrink();
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: loading
            ? const LinearProgressIndicator(semanticsLabel: 'Loading more results')
            : TextButton.icon(
                onPressed: onLoadMore,
                icon: Icon(error == null ? Icons.expand_more : Icons.refresh),
                label: Text(error == null ? 'Load more results' : 'Could not load more. Retry'),
              ),
      ),
    );
  }
}
