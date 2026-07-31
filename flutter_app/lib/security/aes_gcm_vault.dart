import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Envelope encryption for the API key.
/// The random AES-256 master key is held by Keychain/Keystore; only AES-GCM
/// ciphertext, nonce, and MAC are placed in SharedPreferences.
class AesGcmVault {
  static const _masterKeyName = 'couch.vault.master.v1';
  static const _apiKeyEnvelopeName = 'couch.vault.api_key.v1';
  final FlutterSecureStorage secureStorage;
  final Cipher _cipher = AesGcm.with256bits();

  AesGcmVault({FlutterSecureStorage? secureStorage})
      : secureStorage = secureStorage ?? const FlutterSecureStorage();

  Future<SecretKey> _masterKey() async {
    final encoded = await secureStorage.read(key: _masterKeyName);
    if (encoded != null) return SecretKey(base64Url.decode(encoded));
    final bytes = Uint8List.fromList(List<int>.generate(32, (_) => Random.secure().nextInt(256)));
    await secureStorage.write(key: _masterKeyName, value: base64UrlEncode(bytes));
    return SecretKey(bytes);
  }

  Future<void> writeApiKey(String value) async {
    final nonce = Uint8List.fromList(List<int>.generate(12, (_) => Random.secure().nextInt(256)));
    final box = await _cipher.encrypt(
      utf8.encode(value),
      secretKey: await _masterKey(),
      nonce: nonce,
      aad: utf8.encode('couch-api-key:v1'),
    );
    final envelope = jsonEncode({
      'v': 1,
      'n': base64UrlEncode(box.nonce),
      'c': base64UrlEncode(box.cipherText),
      't': base64UrlEncode(box.mac.bytes),
    });
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_apiKeyEnvelopeName, envelope);
  }

  Future<String?> readApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_apiKeyEnvelopeName);
    if (raw == null) return null;
    final e = jsonDecode(raw) as Map<String, dynamic>;
    final clear = await _cipher.decrypt(
      SecretBox(
        base64Url.decode(e['c'] as String),
        nonce: base64Url.decode(e['n'] as String),
        mac: Mac(base64Url.decode(e['t'] as String)),
      ),
      secretKey: await _masterKey(),
      aad: utf8.encode('couch-api-key:v1'),
    );
    return utf8.decode(clear);
  }

  Future<void> destroy() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_apiKeyEnvelopeName);
    await secureStorage.delete(key: _masterKeyName);
  }
}
