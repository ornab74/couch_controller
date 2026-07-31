import 'dart:async';
import 'dart:convert';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'local_packet_crypto.dart';

class BleCouchTransport {
  BleCouchTransport({required this.crypto});
  final LocalPacketCrypto crypto;

  static final Guid serviceUuid = Guid('8d7b0001-32ad-4c59-b7f2-5c60a39d8830');
  static final Guid commandUuid = Guid('8d7b0002-32ad-4c59-b7f2-5c60a39d8830');
  static final Guid telemetryUuid = Guid('8d7b0003-32ad-4c59-b7f2-5c60a39d8830');

  BluetoothDevice? _device;
  BluetoothCharacteristic? _command;
  BluetoothCharacteristic? _telemetry;
  StreamSubscription<List<int>>? _telemetrySub;
  final StreamController<Map<String, dynamic>> _messages = StreamController.broadcast();
  String _buffer = '';

  Stream<Map<String, dynamic>> get messages => _messages.stream;

  Future<List<ScanResult>> scan({Duration timeout = const Duration(seconds: 8)}) async {
    final found = <ScanResult>[];
    final sub = FlutterBluePlus.onScanResults.listen((results) {
      for (final result in results) {
        final matches = result.advertisementData.serviceUuids.contains(serviceUuid);
        if (matches && !found.any((e) => e.device.remoteId == result.device.remoteId)) found.add(result);
      }
    });
    await FlutterBluePlus.startScan(withServices: [serviceUuid], timeout: timeout);
    await Future<void>.delayed(timeout);
    await FlutterBluePlus.stopScan();
    await sub.cancel();
    return found;
  }

  Future<void> connect(BluetoothDevice device) async {
    await disconnect();
    await device.connect(timeout: const Duration(seconds: 12));
    final services = await device.discoverServices();
    final service = services.firstWhere((s) => s.uuid == serviceUuid);
    _command = service.characteristics.firstWhere((c) => c.uuid == commandUuid);
    _telemetry = service.characteristics.firstWhere((c) => c.uuid == telemetryUuid);
    await _telemetry!.setNotifyValue(true);
    _telemetrySub = _telemetry!.onValueReceived.listen(_onBytes, onError: _messages.addError);
    _device = device;
  }

  void _onBytes(List<int> bytes) {
    _buffer += utf8.decode(bytes, allowMalformed: true);
    while (_buffer.contains('\n')) {
      final split = _buffer.indexOf('\n');
      final line = _buffer.substring(0, split).trim();
      _buffer = _buffer.substring(split + 1);
      if (line.isEmpty) continue;
      try {
        crypto.open(jsonDecode(line) as Map<String, dynamic>).then(_messages.add).catchError(_messages.addError);
      } catch (e) {
        _messages.addError(e);
      }
    }
  }

  Future<void> send(Map<String, dynamic> payload) async {
    final characteristic = _command;
    if (characteristic == null) throw StateError('BLE couch is not connected');
    final bytes = utf8.encode('${jsonEncode(await crypto.seal(payload))}\n');
    final chunkSize = ((_device?.mtuNow ?? 23) - 3).clamp(20, 244);
    for (var i = 0; i < bytes.length; i += chunkSize) {
      final end = (i + chunkSize).clamp(0, bytes.length);
      await characteristic.write(bytes.sublist(i, end), withoutResponse: true);
    }
  }

  Future<void> disconnect() async {
    await _telemetrySub?.cancel();
    await _device?.disconnect();
    _telemetrySub = null;
    _device = null;
    _command = null;
    _telemetry = null;
  }

  Future<void> dispose() async {
    await disconnect();
    await _messages.close();
  }
}
