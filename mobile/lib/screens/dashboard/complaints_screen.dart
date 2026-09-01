import 'dart:convert';
import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../utils/theme.dart';

class ComplaintsScreen extends StatefulWidget {
  const ComplaintsScreen({Key? key}) : super(key: key);

  @override
  State<ComplaintsScreen> createState() => _ComplaintsScreenState();
}

class _ComplaintsScreenState extends State<ComplaintsScreen> {
  final _apiService = ApiService();
  bool _isLoading = true;
  String? _error;
  List<dynamic> _allComplaints = [];
  List<dynamic> _filteredComplaints = [];
  final _searchController = TextEditingController();
  String _selectedStatus = 'All';

  @override
  void initState() {
    super.initState();
    _fetchComplaints();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _fetchComplaints() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final response = await _apiService.get('/api/complaints/');
      if (response.statusCode == 200) {
        setState(() {
          _allComplaints = jsonDecode(response.body);
          _applyFilters();
          _isLoading = false;
        });
      } else {
        setState(() {
          _error = 'Failed to load complaints. Status code: ${response.statusCode}';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString().replaceAll('Exception:', '').trim();
        _isLoading = false;
      });
    }
  }

  void _applyFilters() {
    String query = _searchController.text.toLowerCase();
    setState(() {
      _filteredComplaints = _allComplaints.where((complaint) {
        bool matchesSearch = false;
        final id = (complaint['complaint_id'] ?? '').toString().toLowerCase();
        final brand = (complaint['brand_name'] ?? '').toString().toLowerCase();
        final model = (complaint['model_name'] ?? '').toString().toLowerCase();
        final desc = (complaint['complaint_description'] ?? '').toString().toLowerCase();

        if (id.contains(query) ||
            brand.contains(query) ||
            model.contains(query) ||
            desc.contains(query)) {
          matchesSearch = true;
        }

        bool matchesStatus = true;
        if (_selectedStatus != 'All') {
          matchesStatus = complaint['status'] == _selectedStatus;
        }

        return matchesSearch && matchesStatus;
      }).toList();
    });
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'Open':
        return const Color(0xFFFFB020);
      case 'Closed':
        return const Color(0xFF45D483);
      case 'On Hold':
        return AppTheme.primaryRed;
      default:
        return AppTheme.mutedText;
    }
  }

  void _showComplaintDetails(Map<String, dynamic> complaint) {
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Complaint #${complaint['complaint_id']}'),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: _getStatusColor(complaint['status']).withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: _getStatusColor(complaint['status'])),
                ),
                child: Text(
                  complaint['status'] ?? 'Open',
                  style: TextStyle(
                    fontSize: 12,
                    color: _getStatusColor(complaint['status']),
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          content: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                _buildDetailRow('Date', complaint['date'] ?? 'N/A'),
                _buildDetailRow('Vehicle', '${complaint['brand_name'] ?? ''} ${complaint['model_name'] ?? ''} (${complaint['year_range'] ?? 'N/A'})'),
                _buildDetailRow('SKU', complaint['sku_code'] ?? 'N/A'),
                _buildDetailRow('Reporter', complaint['reported_by_name'] ?? 'N/A'),
                _buildDetailRow('Country/Channel', '${complaint['country_name'] ?? 'N/A'} / ${complaint['channel_name'] ?? 'N/A'}'),
                _buildDetailRow('Material/Series', '${complaint['material_name'] ?? 'N/A'} / ${complaint['series_name'] ?? 'N/A'}'),
                const Divider(height: 24),
                const Text('Description', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text(complaint['complaint_description'] ?? 'No description provided.'),
                if (complaint['justification_from_factory'] != null && complaint['justification_from_factory'] != 'Not Provided') ...[
                  const SizedBox(height: 12),
                  const Text('Factory Justification', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text(complaint['justification_from_factory']),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4.0),
      child: RichText(
        text: TextSpan(
          style: const TextStyle(color: Color(0xFFD6D6D6), fontSize: 14),
          children: [
            TextSpan(text: '$label: ', style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white)),
            TextSpan(text: value),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Complaints'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _fetchComplaints,
          ),
        ],
      ),
      body: Column(
        children: [
          // Filter & Search Header
          Padding(
            padding: const EdgeInsets.all(12.0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    decoration: InputDecoration(
                      hintText: 'Search complaints...',
                      prefixIcon: const Icon(Icons.search),
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    onChanged: (val) => _applyFilters(),
                  ),
                ),
                const SizedBox(width: 12),
                DropdownButton<String>(
                  value: _selectedStatus,
                  dropdownColor: AppTheme.elevatedCard,
                  underline: const SizedBox(),
                  items: ['All', 'Open', 'Closed', 'On Hold'].map((status) {
                    return DropdownMenuItem<String>(
                      value: status,
                      child: Text(status),
                    );
                  }).toList(),
                  onChanged: (val) {
                    if (val != null) {
                      setState(() {
                        _selectedStatus = val;
                        _applyFilters();
                      });
                    }
                  },
                ),
              ],
            ),
          ),
          // Main Content
          Expanded(
            child: RefreshIndicator(
              onRefresh: _fetchComplaints,
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
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
                                  onPressed: _fetchComplaints,
                                  child: const Text('Retry'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : _filteredComplaints.isEmpty
                          ? const Center(child: Text('No complaints found.'))
                          : ListView.builder(
                              itemCount: _filteredComplaints.length,
                              itemBuilder: (context, index) {
                                final complaint = _filteredComplaints[index];
                                final status = complaint['status'] ?? 'Open';
                                final id = complaint['complaint_id'] ?? 'N/A';
                                final title = '${complaint['brand_name'] ?? ''} ${complaint['model_name'] ?? ''}';
                                final subtitle = complaint['complaint_description'] ?? '';

                                return Card(
                                  margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                  child: ListTile(
                                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                                    title: Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Text(
                                          'ID: $id',
                                          style: const TextStyle(fontWeight: FontWeight.bold, color: AppTheme.primaryRed),
                                        ),
                                        Container(
                                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                          decoration: BoxDecoration(
                                            color: _getStatusColor(status).withValues(alpha: 0.1),
                                            borderRadius: BorderRadius.circular(8),
                                            border: Border.all(color: _getStatusColor(status).withValues(alpha: 0.5)),
                                          ),
                                          child: Text(
                                            status,
                                            style: TextStyle(
                                              fontSize: 10,
                                              color: _getStatusColor(status),
                                              fontWeight: FontWeight.bold,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                    subtitle: Padding(
                                      padding: const EdgeInsets.only(top: 6.0),
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            title,
                                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500),
                                          ),
                                          const SizedBox(height: 4),
                                          Text(
                                            subtitle,
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(color: AppTheme.mutedText, fontSize: 13),
                                          ),
                                        ],
                                      ),
                                    ),
                                    trailing: const Icon(Icons.arrow_forward_ios, size: 16),
                                    onTap: () => _showComplaintDetails(complaint),
                                  ),
                                );
                              },
                            ),
            ),
          ),
        ],
      ),
    );
  }
}
