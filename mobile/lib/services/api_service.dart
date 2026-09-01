import 'dart:convert';
import 'dart:async';
import 'package:http/http.dart' as http;
import '../config/environment.dart';
import '../utils/secure_storage.dart';

class ApiService {
  static const Duration _requestTimeout = Duration(seconds: 20);
  static const int _maxGetAttempts = 3;
  static final ApiService _instance = ApiService._internal();
  final _secureStorage = SecureStorage();

  factory ApiService() {
    return _instance;
  }

  ApiService._internal();

  // Construct HTTP headers and inject authorization token if available
  Future<Map<String, String>> _getHeaders({bool isMultipart = false}) async {
    final token = await _secureStorage.getToken();
    final headers = <String, String>{};
    if (!isMultipart) {
      headers['Content-Type'] = 'application/json; charset=UTF-8';
    }
    if (token != null) {
      headers['Authorization'] = 'Token $token';
    }
    return headers;
  }

  // GET Request
  Future<http.Response> get(String endpoint) async {
    final url = Uri.parse('${Environment.apiUrl}$endpoint');
    final headers = await _getHeaders();
    Object? lastError;
    for (var attempt = 0; attempt < _maxGetAttempts; attempt++) {
      try {
        final response = await http
            .get(url, headers: headers)
            .timeout(_requestTimeout);
        final isTransient = response.statusCode == 502 ||
            response.statusCode == 503 ||
            response.statusCode == 504;
        if (!isTransient || attempt == _maxGetAttempts - 1) {
          return response;
        }
      } catch (error) {
        lastError = error;
        if (attempt == _maxGetAttempts - 1) rethrow;
      }

      // A short exponential backoff covers backend/database cold starts without
      // delaying authentication or permission failures.
      await Future<void>.delayed(
        Duration(milliseconds: 300 * (1 << attempt)),
      );
    }
    throw StateError('GET request failed after retries: $lastError');
  }

  // POST Request
  Future<http.Response> post(String endpoint, Map<String, dynamic> body) async {
    final url = Uri.parse('${Environment.apiUrl}$endpoint');
    final headers = await _getHeaders();
    return http.post(
      url, 
      headers: headers, 
      body: jsonEncode(body),
    ).timeout(_requestTimeout);
  }

  // PATCH Request
  Future<http.Response> patch(String endpoint, Map<String, dynamic> body) async {
    final url = Uri.parse('${Environment.apiUrl}$endpoint');
    final headers = await _getHeaders();
    return http.patch(
      url, 
      headers: headers, 
      body: jsonEncode(body),
    ).timeout(_requestTimeout);
  }

  // DELETE Request
  Future<http.Response> delete(String endpoint) async {
    final url = Uri.parse('${Environment.apiUrl}$endpoint');
    final headers = await _getHeaders();
    return http.delete(url, headers: headers).timeout(_requestTimeout);
  }
}
