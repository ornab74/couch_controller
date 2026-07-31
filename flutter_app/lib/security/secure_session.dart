import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:http/http.dart' as http;

class SecureSession {
  final String baseUrl;
  final String apiKey;
  final String? pinnedIdentityFingerprint;
  final http.Client client;
  final X25519 _x25519 = X25519();
  final Ed25519 _ed25519 = Ed25519();
  final Cipher _cipher = AesGcm.with256bits();

  String? sessionId;
  SecretKey? _sessionKey;
  int _sequence = 0;
  String? peerFingerprint;

  SecureSession({required this.baseUrl, required this.apiKey, this.pinnedIdentityFingerprint, http.Client? client})
      : client = client ?? http.Client();

  static Uint8List _random(int count) => Uint8List.fromList(List<int>.generate(count, (_) => Random.secure().nextInt(256)));
  static String _b64(List<int> value) => base64UrlEncode(value).replaceAll('=', '');
  static Uint8List _unb64(String value) => base64Url.decode(base64Url.normalize(value));

  Future<void> connect() async {
    final clientPair = await _x25519.newKeyPair();
    final clientPub = await clientPair.extractPublicKey();
    final clientNonce = _random(32);
    final response = await client.post(
      Uri.parse('$baseUrl/v2/security/session'),
      headers: {'content-type': 'application/json'},
      body: jsonEncode({'api_key': apiKey, 'client_public_key': _b64(clientPub.bytes), 'client_nonce': _b64(clientNonce)}),
    );
    if (response.statusCode != 200) throw StateError('Secure pairing failed (${response.statusCode})');
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final identityPub = SimplePublicKey(_unb64(body['identity_public_key'] as String), type: KeyPairType.ed25519);
    peerFingerprint = body['identity_fingerprint'] as String;
    if (pinnedIdentityFingerprint != null && pinnedIdentityFingerprint != peerFingerprint) {
      throw StateError('Couch identity fingerprint mismatch. Pairing aborted.');
    }
    final transcript = utf8.encode([
      body['session_id'],
      _b64(clientPub.bytes),
      body['server_public_key'],
      _b64(clientNonce),
      body['server_nonce'],
    ].join('|'));
    final valid = await _ed25519.verify(
      transcript,
      signature: Signature(_unb64(body['signature'] as String), publicKey: identityPub),
    );
    if (!valid) throw StateError('Invalid couch identity signature.');

    final shared = await _x25519.sharedSecretKey(
      keyPair: clientPair,
      remotePublicKey: SimplePublicKey(_unb64(body['server_public_key'] as String), type: KeyPairType.x25519),
    );
    _sessionKey = await Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
      secretKey: shared,
      nonce: [...clientNonce, ..._unb64(body['server_nonce'] as String)],
      info: utf8.encode('couch-control/session/v2'),
    );
    sessionId = body['session_id'] as String;
    _sequence = 0;
  }

  Future<Map<String, dynamic>> request(String method, String path, [Map<String, dynamic>? payload]) async {
    if (_sessionKey == null || sessionId == null) await connect();
    final seq = ++_sequence;
    final nonce = _random(12);
    final aad = utf8.encode('$sessionId:$seq');
    final plain = utf8.encode(jsonEncode({'method': method, 'path': path, 'body': payload ?? const {}}));
    final box = await _cipher.encrypt(plain, secretKey: _sessionKey!, nonce: nonce, aad: aad);
    final response = await client.post(
      Uri.parse('$baseUrl/v2/secure'),
      headers: {'content-type': 'application/json'},
      body: jsonEncode({'session_id': sessionId, 'sequence': seq, 'nonce': _b64(nonce), 'ciphertext': _b64(box.cipherText), 'tag': _b64(box.mac.bytes)}),
    );
    if (response.statusCode == 401 || response.statusCode == 409) {
      _sessionKey = null;
      sessionId = null;
      throw StateError('Secure session expired or replay rejected');
    }
    if (response.statusCode != 200) throw StateError('Secure couch request failed (${response.statusCode})');
    final envelope = jsonDecode(response.body) as Map<String, dynamic>;
    final result = await _cipher.decrypt(
      SecretBox(_unb64(envelope['ciphertext'] as String), nonce: _unb64(envelope['nonce'] as String), mac: Mac(_unb64(envelope['tag'] as String))),
      secretKey: _sessionKey!,
      aad: utf8.encode('$sessionId:${envelope['sequence']}'),
    );
    return jsonDecode(utf8.decode(result)) as Map<String, dynamic>;
  }

  void dispose() => client.close();
}
