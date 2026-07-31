import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

/// Encrypts and authenticates packets for USB/BLE using a pre-provisioned
/// bootstrap key. Every packet has a random nonce, timestamp and monotonic
/// sequence number. The couch firmware must reject stale/replayed packets.
class LocalPacketCrypto {
  LocalPacketCrypto(this.bootstrapSecret, {this.couchId = 'couch-hat-v1'});

  final String bootstrapSecret;
  final String couchId;
  final AesGcm _aes = AesGcm.with256bits();
  int _sequence = 0;

  Future<SecretKey> _deriveKey() async {
    final hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
    return hkdf.deriveKey(
      secretKey: SecretKey(utf8.encode(bootstrapSecret)),
      nonce: utf8.encode('couch-controller-local-v1'),
      info: utf8.encode(couchId),
    );
  }

  Future<Map<String, dynamic>> seal(Map<String, dynamic> payload) async {
    final nonce = Uint8List.fromList(List<int>.generate(12, (_) => Random.secure().nextInt(256)));
    final seq = ++_sequence;
    final header = <String, dynamic>{
      'v': 1,
      'couch_id': couchId,
      'sequence': seq,
      'timestamp_ms': DateTime.now().millisecondsSinceEpoch,
    };
    final aad = utf8.encode(jsonEncode(header));
    final box = await _aes.encrypt(
      utf8.encode(jsonEncode(payload)),
      secretKey: await _deriveKey(),
      nonce: nonce,
      aad: aad,
    );
    return {
      ...header,
      'nonce': base64UrlEncode(box.nonce),
      'ciphertext': base64UrlEncode(box.cipherText),
      'tag': base64UrlEncode(box.mac.bytes),
    };
  }

  Future<Map<String, dynamic>> open(Map<String, dynamic> envelope) async {
    final header = <String, dynamic>{
      'v': envelope['v'],
      'couch_id': envelope['couch_id'],
      'sequence': envelope['sequence'],
      'timestamp_ms': envelope['timestamp_ms'],
    };
    final clear = await _aes.decrypt(
      SecretBox(
        base64Url.decode(base64Url.normalize(envelope['ciphertext'] as String)),
        nonce: base64Url.decode(base64Url.normalize(envelope['nonce'] as String)),
        mac: Mac(base64Url.decode(base64Url.normalize(envelope['tag'] as String))),
      ),
      secretKey: await _deriveKey(),
      aad: utf8.encode(jsonEncode(header)),
    );
    return jsonDecode(utf8.decode(clear)) as Map<String, dynamic>;
  }
}
