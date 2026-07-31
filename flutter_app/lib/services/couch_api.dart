import 'dart:async';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/telemetry.dart';
import '../security/aes_gcm_vault.dart';
import '../security/secure_session.dart';
import 'ble_couch_transport.dart';
import 'local_packet_crypto.dart';
import 'transport_config.dart';
import 'usb_hat_transport.dart';

class ApiConfiguration extends TransportConfiguration {
  const ApiConfiguration({
    required super.kind,
    required super.baseUrl,
    required super.apiKey,
    super.usbPort,
    super.baudRate,
    super.bleDeviceId,
    super.pinnedFingerprint,
  });
}

class CouchApi {
  static const _urlKey = 'couch.server.url';
  static const _kindKey = 'couch.transport.kind';
  static const _usbKey = 'couch.transport.usb_port';
  static const _bleKey = 'couch.transport.ble_id';
  static const _fingerprintKey = 'couch.identity.fingerprint';

  final AesGcmVault _vault = AesGcmVault();
  ApiConfiguration? _config;
  SecureSession? _session;
  UsbHatTransport? _usb;
  BleCouchTransport? _ble;
  CouchTelemetry _lastTelemetry = CouchTelemetry.disconnected();

  Future<ApiConfiguration> loadConfiguration() async {
    final prefs = await SharedPreferences.getInstance();
    final index = prefs.getInt(_kindKey) ?? TransportKind.localApi.index;
    final kind = TransportKind.values[index.clamp(0, TransportKind.values.length - 1)];
    _config = ApiConfiguration(
      kind: kind,
      baseUrl: prefs.getString(_urlKey) ?? 'http://127.0.0.1:8787',
      apiKey: await _vault.readApiKey() ?? 'dev-couch-key',
      usbPort: prefs.getString(_usbKey) ?? '/dev/ttyACM0',
      bleDeviceId: prefs.getString(_bleKey) ?? 'COUCH-HAT',
      pinnedFingerprint: prefs.getString(_fingerprintKey),
    );
    await _configureTransport();
    return config;
  }

  Future<void> saveConfiguration(ApiConfiguration value) async {
    if (value.apiKey.trim().isEmpty) throw ArgumentError('A couch key is required.');
    final prefs = await SharedPreferences.getInstance();
    final normalized = value.baseUrl.replaceAll(RegExp(r'/+$'), '');
    await prefs.setInt(_kindKey, value.kind.index);
    await prefs.setString(_urlKey, normalized);
    await prefs.setString(_usbKey, value.usbPort);
    await prefs.setString(_bleKey, value.bleDeviceId);
    if (value.pinnedFingerprint?.isNotEmpty == true) await prefs.setString(_fingerprintKey, value.pinnedFingerprint!);
    await _vault.writeApiKey(value.apiKey);
    _config = ApiConfiguration(
      kind: value.kind,
      baseUrl: normalized,
      apiKey: value.apiKey,
      usbPort: value.usbPort,
      baudRate: value.baudRate,
      bleDeviceId: value.bleDeviceId,
      pinnedFingerprint: value.pinnedFingerprint,
    );
    await _configureTransport();
  }

  ApiConfiguration get config => _config ?? (throw StateError('Configuration not loaded'));
  String? get peerFingerprint => _session?.peerFingerprint;

  Future<void> _configureTransport() async {
    _session?.dispose();
    await _usb?.dispose();
    await _ble?.dispose();
    _session = null;
    _usb = null;
    _ble = null;

    if (config.kind == TransportKind.localApi || config.kind == TransportKind.cloudApi) {
      if (config.kind == TransportKind.cloudApi && !config.baseUrl.startsWith('https://')) {
        throw StateError('Cloud transport requires an https:// endpoint.');
      }
      _session = SecureSession(baseUrl: config.baseUrl, apiKey: config.apiKey, pinnedIdentityFingerprint: config.pinnedFingerprint);
    } else if (config.kind == TransportKind.usbHat) {
      final transport = UsbHatTransport(crypto: LocalPacketCrypto(config.apiKey));
      await transport.connect(config.usbPort, baudRate: config.baudRate);
      transport.messages.listen(_consumeLocalMessage);
      _usb = transport;
    } else {
      final transport = BleCouchTransport(crypto: LocalPacketCrypto(config.apiKey));
      final results = await transport.scan();
      final wanted = config.bleDeviceId.trim().toLowerCase();
      final matches = results.where((r) {
        final id = r.device.remoteId.str.toLowerCase();
        final name = r.advertisementData.advName.toLowerCase();
        return wanted.isEmpty || id == wanted || name == wanted || name.contains(wanted);
      }).toList();
      if (matches.isEmpty) throw StateError('BLE couch "${config.bleDeviceId}" not found.');
      await transport.connect(matches.first.device);
      transport.messages.listen(_consumeLocalMessage);
      _ble = transport;
    }
  }

  void _consumeLocalMessage(Map<String, dynamic> message) {
    final telemetry = message['telemetry'];
    if (telemetry is Map<String, dynamic>) _lastTelemetry = CouchTelemetry.fromJson(telemetry);
  }

  Future<Map<String, dynamic>> _request(String method, String path, [Map<String, dynamic>? body]) async {
    if (config.kind == TransportKind.localApi || config.kind == TransportKind.cloudApi) {
      return (_session ?? (throw StateError('Secure HTTP session not initialized'))).request(method, path, body);
    }
    final packet = {'method': method, 'path': path, 'body': body ?? <String, dynamic>{}};
    if (config.kind == TransportKind.usbHat) {
      await (_usb ?? (throw StateError('USB HAT not connected'))).send(packet);
    } else {
      await (_ble ?? (throw StateError('BLE transport not connected; scan and select the couch HAT first'))).send(packet);
    }
    return {'accepted': true};
  }

  Future<CouchTelemetry> telemetry() async {
    if (config.kind == TransportKind.localApi || config.kind == TransportKind.cloudApi) {
      return CouchTelemetry.fromJson(await _request('GET', '/v1/telemetry'));
    }
    await _request('GET', '/v1/telemetry');
    return _lastTelemetry;
  }

  Future<void> drive({required double throttle, required double steering}) async =>
      _request('POST', '/v1/drive', {'throttle': throttle.clamp(-1.0, 1.0), 'steering': steering.clamp(-1.0, 1.0)});
  Future<void> setArmed(bool armed) async => _request('POST', '/v1/arm', {'armed': armed});
  Future<void> setCollisionAvoidance(bool enabled) async => _request('POST', '/v1/safety/collision-avoidance', {'enabled': enabled});
  Future<void> emergencyStop() async => _request('POST', '/v1/estop');
  Future<void> clearEmergencyStop() async => _request('POST', '/v1/estop/clear');

  Future<void> dispose() async {
    _session?.dispose();
    await _usb?.dispose();
    await _ble?.dispose();
  }
}
