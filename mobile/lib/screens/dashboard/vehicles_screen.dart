import 'dart:convert';
import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../utils/theme.dart';
import '../../widgets/pagination_footer.dart';

class VehiclesScreen extends StatefulWidget {
  const VehiclesScreen({Key? key}) : super(key: key);

  @override
  State<VehiclesScreen> createState() => _VehiclesScreenState();
}

class _VehiclesScreenState extends State<VehiclesScreen> {
  final _apiService = ApiService();
  bool _isLoading = true;
  bool _isLoadingMore = false;
  int _requestGeneration = 0;
  String? _error;
  List<dynamic> _allVehicles = [];
  List<dynamic> _filteredVehicles = [];
  final _searchController = TextEditingController();
  final _scrollController = ScrollController();
  String? _nextEndpoint;

  @override
  void initState() {
    super.initState();
    _fetchVehicles();
    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 240 && _nextEndpoint != null && !_isLoading && !_isLoadingMore) {
        _fetchVehicles(reset: false);
      }
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _fetchVehicles({bool reset = true}) async {
    if (!mounted || (!reset && (_isLoading || _isLoadingMore || _nextEndpoint == null))) return;
    final generation = ++_requestGeneration;
    final endpoint = reset ? '/api/vehicles/' : _nextEndpoint!;
    setState(() {
      _isLoading = reset && _allVehicles.isEmpty;
      _isLoadingMore = !reset;
      _error = null;
    });
    try {
      final response = await _apiService.get(endpoint);
      if (!mounted || generation != _requestGeneration) return;
      if (response.statusCode != 200) {
        throw Exception('Failed to load vehicles. Status code: ${response.statusCode}');
      }
      final decoded = jsonDecode(response.body);
      final items = decoded is Map<String, dynamic>
          ? List<dynamic>.from(decoded['results'] ?? const [])
          : List<dynamic>.from(decoded);
      setState(() {
        _allVehicles = reset ? items : [..._allVehicles, ...items];
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
    _filteredVehicles = _allVehicles.where((vehicle) {
        final submodel = (vehicle['sub_model_name'] ?? '').toString().toLowerCase();
        final code = (vehicle['layout_code'] ?? '').toString().toLowerCase();
        final start = (vehicle['year_start'] ?? '').toString();
        final end = (vehicle['year_end'] ?? '').toString();

        return submodel.contains(query) ||
            code.contains(query) ||
            start.contains(query) ||
            end.contains(query);
      }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Vehicles'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _isLoadingMore ? null : _fetchVehicles,
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
                hintText: 'Search by sub-model, layout code, year...',
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
              onRefresh: _fetchVehicles,
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null && _allVehicles.isEmpty
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
                                  onPressed: _isLoadingMore ? null : _fetchVehicles,
                                  child: const Text('Retry'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : _filteredVehicles.isEmpty
                          ? const Center(child: Text('No vehicles found.'))
                          : ListView.builder(
                              controller: _scrollController,
                              physics: const AlwaysScrollableScrollPhysics(),
                              itemCount: _filteredVehicles.length,
                              itemBuilder: (context, index) {
                                final vehicle = _filteredVehicles[index];
                                final submodel = vehicle['sub_model_name'] ?? 'N/A';
                                final start = vehicle['year_start'] ?? '';
                                final end = vehicle['year_end'] ?? '';
                                final seats = vehicle['number_of_seats'] ?? '-';
                                final doors = vehicle['number_of_doors'] ?? '-';
                                final code = vehicle['layout_code'] ?? 'N/A';

                                return Card(
                                  margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                  child: ListTile(
                                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                                    leading: const CircleAvatar(
                                      backgroundColor: AppTheme.borderRed,
                                      child: Icon(Icons.directions_car, color: Colors.white),
                                    ),
                                    title: Text(
                                      '$submodel ($start - $end)',
                                      style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                                    ),
                                    subtitle: Padding(
                                      padding: const EdgeInsets.only(top: 6.0),
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            'Layout Code: $code',
                                            style: const TextStyle(color: AppTheme.primaryRed, fontWeight: FontWeight.w500),
                                          ),
                                          const SizedBox(height: 4),
                                          Text(
                                            'Seats: $seats • Doors: $doors',
                                            style: const TextStyle(color: AppTheme.mutedText, fontSize: 13),
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
            onLoadMore: () => _fetchVehicles(reset: false),
          ),
        ],
      ),
    );
  }
}
