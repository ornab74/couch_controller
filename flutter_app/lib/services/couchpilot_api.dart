import 'dart:convert';

import 'package:http/http.dart' as http;

class CouchPilotApi {
  CouchPilotApi({
    this.baseUrl = 'http://127.0.0.1:8791',
    this.apiKey = 'dev-autonomy-key',
    http.Client? client,
  }) : _client = client ?? http.Client();

  final String baseUrl;
  final String apiKey;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $apiKey',
        'Content-Type': 'application/json',
      };

  Future<Map<String, dynamic>> health() async {
    final response = await _client.get(Uri.parse('$baseUrl/health'));
    return _decode(response);
  }

  Future<Map<String, dynamic>> telemetry() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/v2/planner/telemetry'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> planDemo({
    double obstacleX = 3.2,
    double obstacleY = .4,
    double obstacleVx = -.15,
  }) async {
    final reference = List.generate(
      28,
      (index) => {'x_m': (index + 1) * .22, 'y_m': .25 * (index / 7).sinApprox()},
    );
    final response = await _client.post(
      Uri.parse('$baseUrl/v2/planner/plan'),
      headers: _headers,
      body: jsonEncode({
        'state': {
          'x_m': 0,
          'y_m': 0,
          'yaw_rad': 0,
          'speed_mps': .15,
          'yaw_rate_rps': 0,
          'position_sigma_m': .12,
          'yaw_sigma_rad': .035,
          'slip_probability': .03,
        },
        'reference': reference,
        'obstacles': [
          {
            'x_m': obstacleX,
            'y_m': obstacleY,
            'vx_mps': obstacleVx,
            'vy_mps': 0,
            'radius_m': .42,
            'confidence': .96,
          }
        ],
      }),
    );
    return _decode(response);
  }

  Future<void> configure({
    required int samples,
    required int scenarios,
    required double riskTail,
  }) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/v2/planner/config'),
      headers: _headers,
      body: jsonEncode({
        'horizon_steps': 28,
        'samples': samples,
        'iterations': 4,
        'cvar_alpha': riskTail,
        'scenario_count': scenarios,
        'max_speed_mps': 1.15,
      }),
    );
    _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    final dynamic decoded = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('CouchPilot ${response.statusCode}: $decoded');
    }
    return decoded as Map<String, dynamic>;
  }

  void dispose() => _client.close();
}

extension on double {
  double sinApprox() {
    final x = this;
    return x - (x * x * x) / 6 + (x * x * x * x * x) / 120;
  }
}
