enum TransportKind { localApi, cloudApi, usbHat, ble }

extension TransportKindLabel on TransportKind {
  String get label => switch (this) {
        TransportKind.localApi => 'Local API',
        TransportKind.cloudApi => 'Cloud API',
        TransportKind.usbHat => 'USB HAT',
        TransportKind.ble => 'Bluetooth LE',
      };
}

class TransportConfiguration {
  final TransportKind kind;
  final String baseUrl;
  final String apiKey;
  final String usbPort;
  final int baudRate;
  final String bleDeviceId;
  final String? pinnedFingerprint;

  const TransportConfiguration({
    required this.kind,
    required this.baseUrl,
    required this.apiKey,
    this.usbPort = '',
    this.baudRate = 115200,
    this.bleDeviceId = '',
    this.pinnedFingerprint,
  });
}
