import 'package:flutter/foundation.dart';

class Environment {
  static const String _configuredApiUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  static String get apiUrl {
    if (_configuredApiUrl.isNotEmpty) {
      return _configuredApiUrl.endsWith('/')
          ? _configuredApiUrl.substring(0, _configuredApiUrl.length - 1)
          : _configuredApiUrl;
    }

    // 10.0.2.2 lets an Android emulator reach the host machine.
    return kIsWeb ? 'http://127.0.0.1:8000' : 'http://10.0.2.2:8000';
  }
}
