import 'package:flutter/foundation.dart';

class Environment {
  static const String _configuredApiUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  static String get apiUrl {
    if (_configuredApiUrl.isNotEmpty) {
      final normalizedUrl = _configuredApiUrl.endsWith('/')
          ? _configuredApiUrl.substring(0, _configuredApiUrl.length - 1)
          : _configuredApiUrl;
      final uri = Uri.tryParse(normalizedUrl);
      if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
        throw StateError('API_BASE_URL must be an absolute URL.');
      }
      if (kReleaseMode && uri.scheme != 'https') {
        throw StateError('API_BASE_URL must use HTTPS in release builds.');
      }
      return normalizedUrl;
    }

    if (kReleaseMode) {
      throw StateError('API_BASE_URL is required in release builds.');
    }

    // 10.0.2.2 lets an Android emulator reach the host machine.
    return kIsWeb ? 'http://127.0.0.1:8000' : 'http://10.0.2.2:8000';
  }
}
