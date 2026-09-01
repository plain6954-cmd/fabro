class DashboardStats {
  final int totalComplaints;
  final int openComplaints;
  final int closedComplaints;
  final int onHoldComplaints;
  final int totalVehicles;
  final int totalSkus;
  final int totalMasterSettings;

  const DashboardStats({
    required this.totalComplaints,
    required this.openComplaints,
    required this.closedComplaints,
    required this.onHoldComplaints,
    required this.totalVehicles,
    required this.totalSkus,
    required this.totalMasterSettings,
  });

  factory DashboardStats.fromJson(Map<String, dynamic> json) {
    return DashboardStats(
      totalComplaints: _readInt(json['total_complaints']),
      openComplaints: _readInt(json['open_complaints']),
      closedComplaints: _readInt(json['closed_complaints']),
      onHoldComplaints: _readInt(json['on_hold_complaints']),
      totalVehicles: _readInt(json['total_vehicles']),
      totalSkus: _readInt(json['total_skus']),
      totalMasterSettings: _readInt(json['total_master_settings'] ?? json['total_settings']),
    );
  }

  static int _readInt(dynamic value) {
    if (value is int) return value;
    if (value is String) return int.tryParse(value) ?? 0;
    return 0;
  }
}
