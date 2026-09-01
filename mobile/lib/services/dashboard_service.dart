import 'dart:convert';
import '../models/dashboard_stats.dart';
import 'api_service.dart';

class DashboardService {
  static final DashboardService _instance = DashboardService._internal();
  final _apiService = ApiService();

  factory DashboardService() {
    return _instance;
  }

  DashboardService._internal();

  Future<DashboardStats> fetchStats() async {
    final response = await _apiService.get('/api/dashboard/');

    if (response.statusCode == 200) {
      return DashboardStats.fromJson(jsonDecode(response.body));
    }

    throw Exception('Failed to load dashboard. Status code: ${response.statusCode}');
  }
}
