import 'package:shared_preferences/shared_preferences.dart';

import '../models/telemetry.dart';
import '../security/aes_gcm_vault.dart';
import '../security/secure_session.dart';

class ApiConfiguration {
  final String baseUrl;
  final String apiKey;
  final String? pinnedFingerprint;
  const ApiConfiguration({required this.baseUrl, required this.apiKey, this.pinnedFingerprint});
}

class CouchApi {
  static const _urlKey = 'couch.server.url';
  static const _fingerprintKey = 'couch.identity.fingerprint';
  final AesGcmVault _vault = AesGcmVault();
  ApiConfiguration? _config;
  SecureSession? _session;

  Future<ApiConfiguration> loadConfiguration() async {
    final prefs = await SharedPreferences.getInstance();
    final value = ApiConfiguration(
      baseUrl: prefs.getString(_urlKey) ?? 'http://127.0.0.1:8787',
      apiKey: await _vault.readApiKey() ?? 'dev-couch-key',
      pinnedFingerprint: prefs.getString(_fingerprintKey),
    );
    _config = value;
    _newSession();
    return value;
  }

  Future<void> saveConfiguration(ApiConfiguration config) async {
    final prefs = await SharedPreferences.getInstance();
    final normalized = config.baseUrl.replaceAll(RegExp(r'/+$'), '');
    await prefs.setString(_urlKey, normalized);
    if (config.pinnedFingerprint != null && config.pinnedFingerprint!.isNotEmpty) {
      await prefs.setString(_fingerprintKey, config.pinnedFingerprint!);
    }
    await _vault.writeApiKey(config.apiKey);
    _config = ApiConfiguration(baseUrl: normalized, apiKey: config.apiKey, pinnedFingerprint: config.pinnedFingerprint);
    _newSession();
  }

  ApiConfiguration get config => _config ?? (throw StateError('Configuration not loaded'));
  String? get peerFingerprint => _session?.peerFingerprint;

  void _newSession() {
    _session?.dispose();
    _session = SecureSession(
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      pinnedIdentityFingerprint: config.pinnedFingerprint,
    );
  }

  Future<Map<String, dynamic>> _request(String method, String path, [Map<String, dynamic>? body]) async {
    final session = _session ?? (throw StateError('Secure session not initialized'));
    return session.request(method, path, body);
  }

  Future<CouchTelemetry> telemetry() async => CouchTelemetry.fromJson(await _request('GET', '/v1/telemetry'));
  Future<void> drive({required double throttle, required double steering}) async {
    await _request('POST', '/v1/drive', {'throttle': throttle.clamp(-1.0, 1.0), 'steering': steering.clamp(-1.0, 1.0)});
  }
  Future<void> setArmed(bool armed) async => _request('POST', '/v1/arm', {'armed': armed});
  Future<void> setCollisionAvoidance(bool enabled) async => _request('POST', '/v1/safety/collision-avoidance', {'enabled': enabled});
  Future<void> emergencyStop() async => _request('POST', '/v1/estop');
  Future<void> clearEmergencyStop() async => _request('POST', '/v1/estop/clear');

  void dispose() => _session?.dispose();
}
