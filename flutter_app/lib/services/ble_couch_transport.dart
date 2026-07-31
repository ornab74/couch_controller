import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

/// BLE is only the byte transport. Payloads must already be encrypted by the
/// SecureSession envelope protocol; BLE pairing alone is never trusted.
class BleCouchTransport {
  static final Guid serviceUuid = Guid('8d7b0001-32ad-4c59-b7f2-5c60a39d8830');
  static final Guid commandUuid = Guid('8d7b0002-32ad-4c59-b7f2-5c60a39d8830');
  static final Guid telemetryUuid = Guid('8d7b0003-32ad-4c59-b7f2-5c60a39d8830');

  BluetoothDevice? _device;
  BluetoothCharacteristic? _command;
  BluetoothCharacteristic? _telemetry;

  Stream<List<int>> get telemetry => _telemetry?.onValueReceived ?? const Stream.empty();

  Future<List<ScanResult>> scan({Duration timeout = const Duration(seconds: 8)}) async {
    final found = <ScanResult>[];
    final sub = FlutterBluePlus.onScanResults.listen((results) {
      for (final r in results) {
        if (r.advertisementData.serviceUuids.contains(serviceUuid) && !found.any((x) => x.device.remoteId == r.device.remoteId)) found.add(r);
      }
    });
    await FlutterBluePlus.startScan(withServices: [serviceUuid], timeout: timeout);
    await Future<void>.delayed(timeout);
    await sub.cancel();
    return found;
  }

  Future<void> connect(BluetoothDevice device) async {
    await device.connect(timeout: const Duration(seconds: 12), license: License.free);
    _device = device;
    final services = await device.discoverServices();
    final service = services.firstWhere((s) => s.uuid == serviceUuid);
    _command = service.characteristics.firstWhere((c) => c.uuid == commandUuid);
    _telemetry = service.characteristics.firstWhere((c) => c.uuid == telemetryUuid);
    await _telemetry!.setNotifyValue(true);
  }

  Future<void> sendEncryptedEnvelope(Map<String, dynamic> envelope) async {
    final characteristic = _command;
    if (characteristic == null) throw StateError('BLE couch is not connected');
    final bytes = Uint8List.fromList(utf8.encode(jsonEncode(envelope)));
    final mtu = (_device?.mtuNow ?? 23) - 3;
    for (var offset = 0; offset < bytes.length; offset += mtu) {
      await characteristic.write(bytes.sublist(offset, (offset + mtu).clamp(0, bytes.length)), withoutResponse: true);
    }
  }

  Future<void> disconnect() async {
    await _device?.disconnect();
    _device = null;
    _command = null;
    _telemetry = null;
  }
}
