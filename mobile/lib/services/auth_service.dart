import 'dart:convert';
import 'api_service.dart';
import '../utils/secure_storage.dart';
import '../models/user.dart';

class AuthService {
  static final AuthService _instance = AuthService._internal();
  final _apiService = ApiService();
  final _secureStorage = SecureStorage();

  factory AuthService() {
    return _instance;
  }

  AuthService._internal();

  // Log in user and store token locally
  Future<UserModel?> login(String username, String password) async {
    final response = await _apiService.post('/api/auth/login/', {
      'username': username,
      'password': password,
    });

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final token = data['token'] as String;
      final userJson = data['user'] as Map<String, dynamic>;
      
      await _secureStorage.saveToken(token);
      return UserModel.fromJson(userJson);
    } else {
      final data = jsonDecode(response.body);
      final error = data['error'] ?? 'Login failed. Please check credentials.';
      throw Exception(error);
    }
  }

  // Register new user
  Future<UserModel?> register(String username, String email, String password) async {
    final response = await _apiService.post('/api/auth/register/', {
      'username': username,
      'email': email,
      'password': password,
    });

    if (response.statusCode == 201) {
      final data = jsonDecode(response.body);
      final token = data['token'] as String;
      final userJson = data['user'] as Map<String, dynamic>;
      
      await _secureStorage.saveToken(token);
      return UserModel.fromJson(userJson);
    } else {
      final errors = jsonDecode(response.body);
      throw Exception(errors.toString());
    }
  }

  // Log out user and revoke token
  Future<void> logout() async {
    try {
      await _apiService.post('/api/auth/logout/', {});
    } catch (_) {
      // Ignore network failure on logout; force local cleanup anyway
    }
    await _secureStorage.deleteToken();
  }

  // Get current user details if token is valid
  Future<UserModel?> getProfile() async {
    final token = await _secureStorage.getToken();
    if (token == null) return null;

    final response = await _apiService.get('/api/user/profile/');
    if (response.statusCode == 200) {
      return UserModel.fromJson(jsonDecode(response.body));
    }
    if (response.statusCode == 401 || response.statusCode == 403) {
      // Only authentication/authorization failures prove the token is unusable.
      await _secureStorage.deleteToken();
      return null;
    }
    throw Exception('The service is temporarily unavailable. Please retry.');
  }

  Future<UserModel> updateProfile({
    required String firstName,
    required String lastName,
    required String email,
  }) async {
    final response = await _apiService.patch('/api/user/profile/', {
      'first_name': firstName,
      'last_name': lastName,
      'email': email,
    });

    if (response.statusCode == 200) {
      return UserModel.fromJson(jsonDecode(response.body));
    }

    final data = jsonDecode(response.body);
    throw Exception(data.toString());
  }
}
