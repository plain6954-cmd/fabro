import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/dashboard_stats.dart';
import '../../providers/auth_provider.dart';
import '../../services/dashboard_service.dart';
import '../../utils/theme.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _dashboardService = DashboardService();
  bool _isLoadingStats = true;
  String? _statsError;
  DashboardStats? _stats;

  @override
  void initState() {
    super.initState();
    _fetchStats();
  }

  Future<void> _fetchStats() async {
    setState(() {
      _isLoadingStats = true;
      _statsError = null;
    });

    try {
      final stats = await _dashboardService.fetchStats();
      if (!mounted) return;
      setState(() {
        _stats = stats;
        _isLoadingStats = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _statsError = e.toString().replaceAll('Exception:', '').trim();
        _isLoadingStats = false;
      });
    }
  }

  void _showComingSoon(String feature) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('$feature will be connected in the next mobile step.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = Provider.of<AuthProvider>(context);

    return Scaffold(
      appBar: AppBar(
        toolbarHeight: 74,
        title: Image.asset(
          'assets/images/fabro-logo.png',
          height: 62,
          fit: BoxFit.contain,
        ),
        actions: [
          PopupMenuButton<String>(
            tooltip: 'Account',
            icon: const Icon(Icons.account_circle_outlined, size: 30),
            color: Theme.of(context).cardColor,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            offset: const Offset(0, 48),
            onSelected: (value) async {
              if (value == 'settings') {
                _showComingSoon('Settings');
                return;
              }

              if (value == 'profile') {
                Navigator.of(context).pushNamed('/profile');
                return;
              }

              if (value == 'logout') {
                await authProvider.logout();
                if (context.mounted) {
                  Navigator.of(context).pushReplacementNamed('/login');
                }
              }
            },
            itemBuilder: (context) => const [
              PopupMenuItem(
                value: 'settings',
                child: ListTile(
                  leading: Icon(Icons.settings_outlined),
                  title: Text('Settings'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: 'profile',
                child: ListTile(
                  leading: Icon(Icons.person_outline),
                  title: Text('Profile'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuDivider(),
              PopupMenuItem(
                value: 'logout',
                child: ListTile(
                  leading: Icon(Icons.logout),
                  title: Text('Logout'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
            ],
          ),
        ],
      ),
      body: Stack(
        children: [
          Positioned.fill(
            child: Image.asset(
              'assets/images/fabro-mobile-background.png',
              fit: BoxFit.cover,
              alignment: Alignment.center,
              errorBuilder: (context, error, stackTrace) => const SizedBox(),
            ),
          ),
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: AppTheme.black.withValues(alpha: 0.78),
              ),
            ),
          ),
          const Positioned.fill(
            child: IgnorePointer(
              child: CustomPaint(painter: _RedDotGridPainter()),
            ),
          ),
          RefreshIndicator(
            onRefresh: _fetchStats,
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(18, 16, 18, 28),
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final isWide = constraints.maxWidth >= 760;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'System Dashboard',
                        style: TextStyle(
                          color: AppTheme.primaryRed,
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          height: 1,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Car Seat Management Portal',
                        style: TextStyle(
                          color: AppTheme.mutedText,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 20),
                      _buildStatisticsSection(isWide: isWide),
                      const SizedBox(height: 24),
                      _buildQuickAccessSection(isWide: isWide),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSectionTitle(IconData icon, String title) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: Colors.white),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Container(height: 1, color: Colors.white.withValues(alpha: 0.09)),
        const SizedBox(height: 12),
      ],
    );
  }

  Widget _buildQuickAccessSection({required bool isWide}) {
    final cards = [
      _QuickAccessData(
        title: 'Add New Complaint',
        description: 'Register a new customer complaint with media attachments and detailed info',
        icon: Icons.add_circle,
        onTap: () => _showComingSoon('Add New Complaint'),
      ),
      _QuickAccessData(
        title: 'View All Complaints',
        description: 'Browse, filter, and manage existing complaints with advanced search',
        icon: Icons.list_alt,
        onTap: () => Navigator.pushNamed(context, '/complaints'),
      ),
      _QuickAccessData(
        title: 'Vehicles',
        description: 'Add and configure vehicle models, brands, and layout code specifications',
        icon: Icons.directions_car,
        onTap: () => Navigator.pushNamed(context, '/vehicles'),
      ),
      _QuickAccessData(
        title: 'SKU Management',
        description: 'Manage product SKUs and inventory with bulk upload capabilities',
        icon: Icons.view_week,
        onTap: () => Navigator.pushNamed(context, '/skus'),
      ),
      _QuickAccessData(
        title: 'Master Settings',
        description: 'Configure master data including channels, countries, and categories',
        icon: Icons.settings,
        onTap: () => _showComingSoon('Master Settings'),
      ),
      _QuickAccessData(
        title: 'Admin Panel',
        description: 'Manage users, groups, permissions and view system activity logs',
        icon: Icons.groups,
        onTap: () => _showComingSoon('Admin Panel'),
      ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSectionTitle(Icons.grid_view, 'Quick Access Options'),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: cards.length,
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: isWide ? 2 : 1,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: isWide ? 3.0 : 3.55,
          ),
          itemBuilder: (context, index) => _buildQuickAccessCard(cards[index]),
        ),
      ],
    );
  }

  Widget _buildQuickAccessCard(_QuickAccessData data) {
    return InkWell(
      onTap: data.onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        decoration: BoxDecoration(
          color: const Color(0xD51A1A1D),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white.withValues(alpha: 0.13)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.28),
              blurRadius: 22,
              offset: const Offset(0, 12),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: AppTheme.primaryRed,
                borderRadius: BorderRadius.circular(10),
                boxShadow: [
                  BoxShadow(
                    color: AppTheme.primaryRed.withValues(alpha: 0.28),
                    blurRadius: 24,
                    offset: const Offset(0, 12),
                  ),
                ],
              ),
              child: Icon(data.icon, color: Colors.white, size: 26),
            ),
            const SizedBox(width: 18),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    data.title,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    data.description,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Color(0xFFB3B3BA),
                      fontSize: 13,
                      height: 1.28,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatisticsSection({required bool isWide}) {
    if (_isLoadingStats) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: 42),
          child: CircularProgressIndicator(),
        ),
      );
    }

    if (_statsError != null) {
      return _buildErrorState();
    }

    final stats = _stats;
    if (stats == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: 42),
          child: Text('No dashboard data available.'),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSectionTitle(Icons.stacked_line_chart, 'System Statistics'),
        GridView.count(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisCount: isWide ? 4 : 2,
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
          childAspectRatio: isWide ? 1.32 : 1.12,
          children: [
            _buildMatrixStatCard(
              icon: Icons.warning_rounded,
              iconColor: AppTheme.primaryRed,
              value: stats.totalComplaints.toString(),
              title: 'Total Complaints',
              footer: Row(
                children: [
                  Expanded(
                    child: _buildMiniStatus(
                      value: stats.openComplaints.toString(),
                      label: 'Open',
                      borderColor: const Color(0xFF0F8C68),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: _buildMiniStatus(
                      value: stats.closedComplaints.toString(),
                      label: 'Closed',
                      borderColor: const Color(0xFF3366B8),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: _buildMiniStatus(
                      value: stats.onHoldComplaints.toString(),
                      label: 'On Hold',
                      borderColor: const Color(0xFFB37B05),
                    ),
                  ),
                ],
              ),
            ),
            _buildMatrixStatCard(
              icon: Icons.directions_car,
              iconColor: const Color(0xFF2F7CFF),
              value: stats.totalVehicles.toString(),
              title: 'Vehicle Models',
            ),
            _buildMatrixStatCard(
              icon: Icons.view_week,
              iconColor: const Color(0xFF10B981),
              value: stats.totalSkus.toString(),
              title: 'SKU Items',
            ),
            _buildMatrixStatCard(
              icon: Icons.settings,
              iconColor: const Color(0xFF7C3AED),
              value: stats.totalMasterSettings.toString(),
              title: 'Master Settings',
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildErrorState() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(22),
      decoration: _dashboardCardDecoration(),
      child: Column(
        children: [
          Icon(Icons.error_outline, size: 42, color: Colors.red.shade400),
          const SizedBox(height: 12),
          Text(
            _statsError!,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _fetchStats,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildMatrixStatCard({
    required IconData icon,
    required Color iconColor,
    required String value,
    required String title,
    Widget? footer,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _dashboardCardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _buildIconTile(icon, iconColor),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 28,
                  fontWeight: FontWeight.w900,
                ),
              ),
              Text(
                title,
                style: const TextStyle(
                  color: Color(0xFFB3B3BA),
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          if (footer != null) footer,
        ],
      ),
    );
  }

  Widget _buildMiniStatus({
    required String value,
    required String label,
    required Color borderColor,
  }) {
    return Container(
      height: 42,
      decoration: BoxDecoration(
        color: const Color(0x702B2B31),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: borderColor.withValues(alpha: 0.82)),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 13,
              fontWeight: FontWeight.w900,
            ),
          ),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: Color(0xFFB3B3BA),
              fontSize: 9,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildIconTile(IconData icon, Color color) {
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(10),
        boxShadow: [
          BoxShadow(
            color: color.withValues(alpha: 0.25),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: Icon(icon, color: Colors.white, size: 26),
    );
  }

  BoxDecoration _dashboardCardDecoration() {
    return BoxDecoration(
      color: const Color(0xD51A1A1D),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: Colors.white.withValues(alpha: 0.13)),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.28),
          blurRadius: 22,
          offset: const Offset(0, 12),
        ),
      ],
    );
  }
}

class _QuickAccessData {
  const _QuickAccessData({
    required this.title,
    required this.description,
    required this.icon,
    required this.onTap,
  });

  final String title;
  final String description;
  final IconData icon;
  final VoidCallback onTap;
}

class _RedDotGridPainter extends CustomPainter {
  const _RedDotGridPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppTheme.primaryRed.withValues(alpha: 0.24)
      ..style = PaintingStyle.fill;

    const spacing = 32.0;
    for (double x = 8; x < size.width; x += spacing) {
      for (double y = 10; y < size.height; y += spacing) {
        canvas.drawCircle(Offset(x, y), 1.15, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
