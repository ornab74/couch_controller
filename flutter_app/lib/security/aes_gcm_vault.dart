import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// AES-256-GCM envelope storage for the API key.
///
/// Android/iOS/macOS use Keystore/Keychain through flutter_secure_storage.
/// Linux first tries Secret Service. If unavailable, it falls back to a
/// per-user 0600 master-key file in the app support directory so desktop
/// development still persists safely without crashing.
class AesGcmVault {
  static const _masterKeyName = 'couch.vault.master.v2';
  static const _apiKeyEnvelopeName = 'couch.vault.api_key.v2';
  static const _fallbackFileName = '.couch_vault_master_v2';

  final FlutterSecureStorage secureStorage;
  final Cipher _cipher = AesGcm.with256bits();

  AesGcmVault({FlutterSecureStorage? secureStorage})
      : secureStorage = secureStorage ?? const FlutterSecureStorage();

  static Uint8List _randomBytes(int length) => Uint8List.fromList(
        List<int>.generate(length, (_) => Random.secure().nextInt(256)),
      );

  Future<File> _fallbackKeyFile() async {
    final directory = await getApplicationSupportDirectory();
    await directory.create(recursive: true);
    return File('${directory.path}/$_fallbackFileName');
  }

  Future<String?> _readSecureMasterKey() async {
    try {
      return await secureStorage.read(key: _masterKeyName);
    } catch (_) {
      return null;
    }
  }

  Future<bool> _writeSecureMasterKey(String value) async {
    try {
      await secureStorage.write(key: _masterKeyName, value: value);
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<SecretKey> _masterKey() async {
    final secureValue = await _readSecureMasterKey();
    if (secureValue != null && secureValue.isNotEmpty) {
      return SecretKey(base64Url.decode(base64Url.normalize(secureValue)));
    }

    if (Platform.isLinux) {
      final fallback = await _fallbackKeyFile();
      if (await fallback.exists()) {
        final encoded = (await fallback.readAsString()).trim();
        if (encoded.isNotEmpty) {
          return SecretKey(base64Url.decode(base64Url.normalize(encoded)));
        }
      }
    }

    final bytes = _randomBytes(32);
    final encoded = base64UrlEncode(bytes);
    final storedSecurely = await _writeSecureMasterKey(encoded);

    if (!storedSecurely) {
      if (!Platform.isLinux) {
        throw StateError('Platform secure storage is unavailable.');
      }
      final fallback = await _fallbackKeyFile();
      await fallback.writeAsString(encoded, flush: true);
      try {
        await Process.run('chmod', ['600', fallback.path]);
      } catch (_) {
        // Best effort only; parent app support directories are user-scoped.
      }
    }

    return SecretKey(bytes);
  }

  Future<void> writeApiKey(String value) async {
    final clean = value.trim();
    if (clean.isEmpty) throw ArgumentError('API key cannot be empty.');

    final nonce = _randomBytes(12);
    final box = await _cipher.encrypt(
      utf8.encode(clean),
      secretKey: await _masterKey(),
      nonce: nonce,
      aad: utf8.encode('couch-api-key:v2'),
    );

    final envelope = jsonEncode({
      'v': 2,
      'n': base64UrlEncode(box.nonce),
      'c': base64UrlEncode(box.cipherText),
      't': base64UrlEncode(box.mac.bytes),
    });

    final prefs = await SharedPreferences.getInstance();
    final saved = await prefs.setString(_apiKeyEnvelopeName, envelope);
    if (!saved) throw StateError('Encrypted API-key envelope was not saved.');
  }

  Future<String?> readApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_apiKeyEnvelopeName);
    if (raw == null || raw.isEmpty) return null;

    try {
      final envelope = jsonDecode(raw) as Map<String, dynamic>;
      final clear = await _cipher.decrypt(
        SecretBox(
          base64Url.decode(base64Url.normalize(envelope['c'] as String)),
          nonce: base64Url.decode(base64Url.normalize(envelope['n'] as String)),
          mac: Mac(base64Url.decode(base64Url.normalize(envelope['t'] as String))),
        ),
        secretKey: await _masterKey(),
        aad: utf8.encode('couch-api-key:v2'),
      );
      return utf8.decode(clear);
    } catch (_) {
      // A stale or corrupt envelope should not prevent the controller from booting.
      await prefs.remove(_apiKeyEnvelopeName);
      return null;
    }
  }

  Future<void> destroy() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_apiKeyEnvelopeName);
    try {
      await secureStorage.delete(key: _masterKeyName);
    } catch (_) {}
    if (Platform.isLinux) {
      final fallback = await _fallbackKeyFile();
      if (await fallback.exists()) await fallback.delete();
    }
  }
}
