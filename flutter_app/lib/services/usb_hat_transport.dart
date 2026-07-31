import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_libserialport/flutter_libserialport.dart';

import 'local_packet_crypto.dart';

class UsbHatTransport {
  UsbHatTransport({required this.crypto});
  final LocalPacketCrypto crypto;
  SerialPort? _port;
  SerialPortReader? _reader;
  StreamSubscription<Uint8List>? _subscription;
  final StreamController<Map<String, dynamic>> _messages = StreamController.broadcast();
  String _buffer = '';

  Stream<Map<String, dynamic>> get messages => _messages.stream;
  List<String> get availablePorts => SerialPort.availablePorts;

  Future<void> connect(String address, {int baudRate = 115200}) async {
    await disconnect();
    final port = SerialPort(address);
    final config = SerialPortConfig()
      ..baudRate = baudRate
      ..bits = 8
      ..stopBits = 1
      ..parity = SerialPortParity.none;
    port.config = config;
    if (!port.openReadWrite()) {
      throw StateError('Could not open USB serial port $address: ${SerialPort.lastError}');
    }
    _port = port;
    _reader = SerialPortReader(port);
    _subscription = _reader!.stream.listen(_onBytes, onError: _messages.addError);
  }

  void _onBytes(Uint8List data) {
    _buffer += utf8.decode(data, allowMalformed: true);
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
    final port = _port;
    if (port == null || !port.isOpen) throw StateError('USB HAT is not connected');
    final envelope = await crypto.seal(payload);
    final data = Uint8List.fromList(utf8.encode('${jsonEncode(envelope)}\n'));
    final written = port.write(data);
    if (written != data.length) throw StateError('USB write incomplete ($written/${data.length})');
  }

  Future<void> disconnect() async {
    await _subscription?.cancel();
    _reader?.close();
    _port?.close();
    _subscription = null;
    _reader = null;
    _port = null;
  }

  Future<void> dispose() async {
    await disconnect();
    await _messages.close();
  }
}
