import 'dart:convert';
import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../utils/theme.dart';
import '../../widgets/pagination_footer.dart';

class SkusScreen extends StatefulWidget {
  const SkusScreen({Key? key}) : super(key: key);

  @override
  State<SkusScreen> createState() => _SkusScreenState();
}

class _SkusScreenState extends State<SkusScreen> {
  final _apiService = ApiService();
  bool _isLoading = true;
  bool _isLoadingMore = false;
  int _requestGeneration = 0;
  String? _error;
  List<dynamic> _allSkus = [];
  List<dynamic> _filteredSkus = [];
  final _searchController = TextEditingController();
  final _scrollController = ScrollController();
  String? _nextEndpoint;

  @override
  void initState() {
    super.initState();
    _fetchSkus();
    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 240 && _nextEndpoint != null && !_isLoading && !_isLoadingMore) {
        _fetchSkus(reset: false);
      }
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _fetchSkus({bool reset = true}) async {
    if (!mounted || (!reset && (_isLoading || _isLoadingMore || _nextEndpoint == null))) return;
    final generation = ++_requestGeneration;
    final endpoint = reset ? '/api/skus/' : _nextEndpoint!;
    setState(() {
      _isLoading = reset && _allSkus.isEmpty;
      _isLoadingMore = !reset;
      _error = null;
    });
    try {
      final response = await _apiService.get(endpoint);
      if (!mounted || generation != _requestGeneration) return;
      if (response.statusCode != 200) {
        throw Exception('Failed to load skus. Status code: ${response.statusCode}');
      }
      final decoded = jsonDecode(response.body);
      final items = decoded is Map<String, dynamic>
          ? List<dynamic>.from(decoded['results'] ?? const [])
          : List<dynamic>.from(decoded);
      setState(() {
        _allSkus = reset ? items : [..._allSkus, ...items];
        _nextEndpoint = decoded is Map<String, dynamic> ? decoded['next'] as String? : null;
        _applyFilters();
      });
    } catch (e) {
      if (!mounted || generation != _requestGeneration) return;
      setState(() {
        _error = e.toString().replaceAll('Exception:', '').trim();
      });
    } finally {
      if (mounted && generation == _requestGeneration) {
        setState(() {
          _isLoading = false;
          _isLoadingMore = false;
        });
      }
    }
  }

  void _applyFilters() {
    String query = _searchController.text.toLowerCase();
    _filteredSkus = _allSkus.where((sku) {
        final code = (sku['code'] ?? '').toString().toLowerCase();
        final desc = (sku['description'] ?? '').toString().toLowerCase();
        final region = (sku['region_name'] ?? '').toString().toLowerCase();

        return code.contains(query) || desc.contains(query) || region.contains(query);
      }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('SKU Management'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _isLoadingMore ? null : _fetchSkus,
          ),
        ],
      ),
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.all(12.0),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Search SKUs by code, description...',
                prefixIcon: const Icon(Icons.search),
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onChanged: (val) => setState(_applyFilters),
            ),
          ),
          // List content
          Expanded(
            child: RefreshIndicator(
              onRefresh: _fetchSkus,
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null && _allSkus.isEmpty
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24.0),
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
                                const SizedBox(height: 12),
                                Text(_error!, textAlign: TextAlign.center),
                                const SizedBox(height: 16),
                                ElevatedButton(
                                  onPressed: _isLoadingMore ? null : _fetchSkus,
                                  child: const Text('Retry'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : _filteredSkus.isEmpty
                          ? const Center(child: Text('No SKUs found.'))
                          : ListView.builder(
                              controller: _scrollController,
                              physics: const AlwaysScrollableScrollPhysics(),
                              itemCount: _filteredSkus.length,
                              itemBuilder: (context, index) {
                                final sku = _filteredSkus[index];
                                final code = sku['code'] ?? 'N/A';
                                final desc = sku['description'] ?? 'No description';
                                final region = sku['region_name'] ?? 'N/A';

                                return Card(
                                  margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                  child: ListTile(
                                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                                    leading: const CircleAvatar(
                                      backgroundColor: AppTheme.borderRed,
                                      child: Icon(Icons.inventory_2, color: Colors.white),
                                    ),
                                    title: Text(
                                      code,
                                      style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                                    ),
                                    subtitle: Padding(
                                      padding: const EdgeInsets.only(top: 4.0),
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            desc,
                                            style: const TextStyle(color: Color(0xFFD6D6D6)),
                                          ),
                                          const SizedBox(height: 4),
                                          Text(
                                            'Region: $region',
                                            style: const TextStyle(color: AppTheme.mutedText, fontSize: 12),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                );
                              },
                            ),
            ),
          ),
          PaginationFooter(
            loading: _isLoadingMore,
            hasMore: _nextEndpoint != null && !_isLoading,
            error: _error,
            onLoadMore: () => _fetchSkus(reset: false),
          ),
        ],
      ),
    );
  }
}
