import 'dart:convert';
import 'dart:async';
import 'package:http/http.dart' as http;
import '../config/environment.dart';
import '../utils/secure_storage.dart';

class ApiService {
  static const Duration _requestTimeout = Duration(seconds: 20);
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
    return http.get(url, headers: headers).timeout(_requestTimeout);
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
