import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SecureStorage {
  static final SecureStorage _instance = SecureStorage._internal();
  final _storage = const FlutterSecureStorage();

  factory SecureStorage() {
    return _instance;
  }

  SecureStorage._internal();

  static const String _tokenKey = 'auth_token';

  // Save authentication token
  Future<void> saveToken(String token) async {
    await _storage.write(key: _tokenKey, value: token);
  }

  // Retrieve stored token
  Future<String?> getToken() async {
    return await _storage.read(key: _tokenKey);
  }

  // Delete token upon logout
  Future<void> deleteToken() async {
    await _storage.delete(key: _tokenKey);
  }
}
