import 'dart:async';
import 'package:flutter/material.dart';

import 'models/telemetry.dart';
import 'services/couch_api.dart';
import 'widgets/analog_stick.dart';
import 'widgets/metric_tile.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const CouchControllerApp());
}

class CouchControllerApp extends StatelessWidget {
  const CouchControllerApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'Couch Controller',
        theme: ThemeData.dark(useMaterial3: true).copyWith(
          scaffoldBackgroundColor: const Color(0xFF03070C),
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1EA7FF), brightness: Brightness.dark),
        ),
        home: const ControllerScreen(),
      );
}

class ControllerScreen extends StatefulWidget {
  const ControllerScreen({super.key});
  @override
  State<ControllerScreen> createState() => _ControllerScreenState();
}

class _ControllerScreenState extends State<ControllerScreen> {
  final CouchApi _api = CouchApi();
  CouchTelemetry _telemetry = CouchTelemetry.disconnected();
  Timer? _pollTimer;
  Timer? _commandTimer;
  double _throttle = 0;
  double _steering = 0;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    await _api.loadConfiguration();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 300), (_) => _poll());
    _commandTimer = Timer.periodic(const Duration(milliseconds: 100), (_) => _sendDrive());
    await _poll();
  }

  Future<void> _poll() async {
    try {
      final t = await _api.telemetry();
      if (mounted) setState(() { _telemetry = t; _error = null; });
    } catch (e) {
      if (mounted) setState(() { _telemetry = CouchTelemetry.disconnected(); _error = '$e'; });
    }
  }

  Future<void> _sendDrive() async {
    if (!_telemetry.armed || _telemetry.estop) return;
    try { await _api.drive(throttle: _throttle, steering: _steering); } catch (_) {}
  }

  Future<void> _toggleArm() async {
    setState(() => _busy = true);
    try { await _api.setArmed(!_telemetry.armed); await _poll(); } finally { if (mounted) setState(() => _busy = false); }
  }

  Future<void> _showConnectionDialog() async {
    final current = _api.config;
    final url = TextEditingController(text: current.baseUrl);
    final key = TextEditingController(text: current.apiKey);
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF0B121B),
        title: const Text('Secure API connection'),
        content: SizedBox(width: 460, child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: url, decoration: const InputDecoration(labelText: 'Server URL', hintText: 'http://192.168.1.50:8787')),
          const SizedBox(height: 12),
          TextField(controller: key, obscureText: true, decoration: const InputDecoration(labelText: 'Bearer API key')),
          const SizedBox(height: 12),
          const Text('API key: AES-256-GCM envelope encryption at rest. Commands: X25519 session key + Ed25519 couch identity signature + AES-GCM packets.', style: TextStyle(color: Color(0xFF8B9CAF), fontSize: 12)),
        ])),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () async {
            await _api.saveConfiguration(ApiConfiguration(baseUrl: url.text.trim(), apiKey: key.text));
            if (context.mounted) Navigator.pop(context, true);
          }, child: const Text('Save')),
        ],
      ),
    );
    if (saved == true) await _poll();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _commandTimer?.cancel();
    _api.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hot = _telemetry.motors.any((m) => m.temperatureC >= 70);
    return Scaffold(
      body: SafeArea(
        child: Container(
          decoration: const BoxDecoration(
            gradient: RadialGradient(center: Alignment(-.3, -.6), radius: 1.4, colors: [Color(0xFF0B1A28), Color(0xFF020407)]),
          ),
          child: Column(children: [
            _TopBar(telemetry: _telemetry, onSettings: _showConnectionDialog),
            _SecurityRibbon(connected: _telemetry.connected, fingerprint: _api.peerFingerprint),
            if (_error != null) Container(width: double.infinity, color: const Color(0xFF5B1919), padding: const EdgeInsets.all(6), child: Text('Server offline — $_error', textAlign: TextAlign.center, maxLines: 1, overflow: TextOverflow.ellipsis)),
            Expanded(child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
              child: Row(children: [
                Expanded(flex: 4, child: _VehiclePanel(telemetry: _telemetry)),
                const SizedBox(width: 14),
                Expanded(flex: 5, child: _ControlsPanel(
                  telemetry: _telemetry,
                  throttle: _throttle,
                  steering: _steering,
                  onThrottle: (v) => _throttle = v,
                  onSteering: (v) => _steering = v,
                )),
                const SizedBox(width: 14),
                SizedBox(width: 230, child: _SidePanel(
                  telemetry: _telemetry,
                  hot: hot,
                  busy: _busy,
                  onArm: _toggleArm,
                  onCollision: (v) async { await _api.setCollisionAvoidance(v); await _poll(); },
                  onEstop: () async { await _api.emergencyStop(); await _poll(); },
                  onClearEstop: () async { await _api.clearEmergencyStop(); await _poll(); },
                )),
              ]),
            )),
          ]),
        ),
      ),
    );
  }
}


class _SecurityRibbon extends StatelessWidget {
  const _SecurityRibbon({required this.connected, required this.fingerprint});
  final bool connected;
  final String? fingerprint;

  @override
  Widget build(BuildContext context) => Container(
    height: 34,
    padding: const EdgeInsets.symmetric(horizontal: 22),
    decoration: const BoxDecoration(
      color: Color(0xCC07111A),
      border: Border(bottom: BorderSide(color: Color(0xFF17344A))),
    ),
    child: Row(children: [
      Icon(connected ? Icons.lock_rounded : Icons.lock_open_rounded, size: 15, color: connected ? const Color(0xFF63E67D) : Colors.orangeAccent),
      const SizedBox(width: 8),
      Text(connected ? 'AES-GCM COMMAND CHANNEL' : 'SECURE CHANNEL OFFLINE', style: const TextStyle(fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w700)),
      const SizedBox(width: 18),
      const Icon(Icons.verified_user_outlined, size: 15, color: Color(0xFF31B7FF)),
      const SizedBox(width: 7),
      Text(fingerprint == null ? 'COUCH IDENTITY: UNPINNED' : 'COUCH ID: $fingerprint', style: const TextStyle(fontSize: 10, color: Color(0xFF8EA6B8))),
      const Spacer(),
      const Text('ANTI-REPLAY • DEAD-MAN 450 ms • COLLISION GUARD', style: TextStyle(fontSize: 9, color: Color(0xFF698296), letterSpacing: .8)),
    ]),
  );
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.telemetry, required this.onSettings});
  final CouchTelemetry telemetry;
  final VoidCallback onSettings;
  @override
  Widget build(BuildContext context) => Container(
    height: 68,
    padding: const EdgeInsets.symmetric(horizontal: 22),
    decoration: const BoxDecoration(color: Color(0xD9060B10), border: Border(bottom: BorderSide(color: Color(0xFF163148)))),
    child: Row(children: [
      const Icon(Icons.weekend_rounded, color: Color(0xFF31B7FF), size: 31),
      const SizedBox(width: 12),
      const Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('COUCH CONTROLLER', style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 2, fontSize: 18)),
        Text('FOUR-MOTOR MANUAL DRIVE', style: TextStyle(color: Color(0xFF31B7FF), letterSpacing: 1.3, fontSize: 10)),
      ]),
      const Spacer(),
      Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7), decoration: BoxDecoration(color: const Color(0xFF0A151E), borderRadius: BorderRadius.circular(99)), child: Row(children: [
        Icon(Icons.circle, size: 10, color: telemetry.connected ? const Color(0xFF63E67D) : Colors.redAccent),
        const SizedBox(width: 7), Text(telemetry.connected ? 'CONNECTED' : 'OFFLINE', style: const TextStyle(fontSize: 11, letterSpacing: 1)),
      ])),
      const SizedBox(width: 18),
      IconButton(onPressed: onSettings, icon: const Icon(Icons.settings_outlined)),
    ]),
  );
}

class _VehiclePanel extends StatelessWidget {
  const _VehiclePanel({required this.telemetry});
  final CouchTelemetry telemetry;
  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(color: const Color(0xB7070D14), borderRadius: BorderRadius.circular(18), border: Border.all(color: const Color(0xFF18344C))),
    child: Column(children: [
      Padding(padding: const EdgeInsets.all(16), child: Row(children: [
        Text(telemetry.armed ? 'ARMED · MANUAL CONTROL' : 'PARKED · DISARMED', style: TextStyle(color: telemetry.armed ? const Color(0xFF36B9FF) : const Color(0xFF8B9CAF), fontWeight: FontWeight.w700, letterSpacing: 1)),
        const Spacer(),
        Icon(telemetry.collisionAvoidance ? Icons.shield : Icons.shield_outlined, color: telemetry.collisionAvoidance ? const Color(0xFF63E67D) : Colors.orange),
      ])),
      Expanded(child: Stack(alignment: Alignment.center, children: [
        Container(margin: const EdgeInsets.all(18), decoration: BoxDecoration(borderRadius: BorderRadius.circular(16), gradient: const RadialGradient(colors: [Color(0xFF10283A), Color(0xFF03070B)]))),
        const _CouchRoverGraphic(),
        Positioned(left: 22, bottom: 18, right: 22, child: Row(children: [
          Expanded(child: MetricTile(icon: Icons.battery_5_bar, label: 'BATTERY', value: '${telemetry.batteryPercent.toStringAsFixed(0)}%')),
          const SizedBox(width: 8),
          Expanded(child: MetricTile(icon: Icons.speed, label: 'SPEED', value: '${telemetry.speedMph.toStringAsFixed(1)} mph')),
          const SizedBox(width: 8),
          Expanded(child: MetricTile(icon: Icons.radar, label: 'OBSTACLE', value: '${telemetry.closestObstacleFt.toStringAsFixed(1)} ft', good: telemetry.closestObstacleFt > 3)),
        ])),
      ])),
    ]),
  );
}

class _CouchRoverGraphic extends StatelessWidget {
  const _CouchRoverGraphic();
  @override
  Widget build(BuildContext context) => SizedBox(width: 350, height: 215, child: Stack(alignment: Alignment.center, children: [
    Positioned(bottom: 32, child: Container(width: 310, height: 32, decoration: BoxDecoration(color: const Color(0xFF061B2A), borderRadius: BorderRadius.circular(9), border: Border.all(color: const Color(0xFF2AC0FF)), boxShadow: const [BoxShadow(color: Color(0x8839B8FF), blurRadius: 22)]))),
    Positioned(bottom: 10, left: 42, child: _wheel()), Positioned(bottom: 10, right: 42, child: _wheel()),
    Positioned(top: 55, child: Icon(Icons.weekend_rounded, size: 220, color: const Color(0xFF172636), shadows: const [Shadow(color: Color(0xFF2DAFFF), blurRadius: 8)])),
    const Positioned(top: 88, left: 73, child: Icon(Icons.light_mode, size: 18, color: Color(0xFF9DEBFF))),
    const Positioned(top: 88, right: 73, child: Icon(Icons.light_mode, size: 18, color: Color(0xFF9DEBFF))),
  ]));
  Widget _wheel() => Container(width: 65, height: 65, decoration: BoxDecoration(shape: BoxShape.circle, color: const Color(0xFF080B0F), border: Border.all(color: const Color(0xFF425267), width: 5)));
}

class _ControlsPanel extends StatelessWidget {
  const _ControlsPanel({required this.telemetry, required this.throttle, required this.steering, required this.onThrottle, required this.onSteering});
  final CouchTelemetry telemetry;
  final double throttle;
  final double steering;
  final ValueChanged<double> onThrottle;
  final ValueChanged<double> onSteering;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: const Color(0xB7070D14), borderRadius: BorderRadius.circular(18), border: Border.all(color: const Color(0xFF18344C))),
    child: Row(children: [
      Expanded(child: AnalogStick(title: 'DRIVE', subtitle: 'BACK / FORWARD', axis: Axis.vertical, enabled: telemetry.armed && !telemetry.estop, onChanged: onThrottle)),
      Container(width: 1, margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 35), color: const Color(0xFF17344D)),
      Expanded(child: AnalogStick(title: 'STEER', subtitle: 'LEFT / RIGHT', axis: Axis.horizontal, enabled: telemetry.armed && !telemetry.estop, onChanged: onSteering)),
    ]),
  );
}

class _SidePanel extends StatelessWidget {
  const _SidePanel({required this.telemetry, required this.hot, required this.busy, required this.onArm, required this.onCollision, required this.onEstop, required this.onClearEstop});
  final CouchTelemetry telemetry;
  final bool hot;
  final bool busy;
  final VoidCallback onArm;
  final ValueChanged<bool> onCollision;
  final VoidCallback onEstop;
  final VoidCallback onClearEstop;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: const Color(0xB7070D14), borderRadius: BorderRadius.circular(18), border: Border.all(color: const Color(0xFF18344C))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('SYSTEM', style: TextStyle(color: Color(0xFF8FA2B7), fontWeight: FontWeight.w700, letterSpacing: 1)),
      const SizedBox(height: 10),
      _status(Icons.bolt, 'Bus voltage', '${telemetry.batteryVoltage.toStringAsFixed(1)} V'),
      _status(Icons.explore, 'Heading', '${telemetry.headingDeg.toStringAsFixed(0)}°'),
      _status(Icons.device_thermostat, 'Motor thermal', hot ? 'HOT' : 'NORMAL', good: !hot),
      const Divider(height: 25),
      SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Collision avoidance', style: TextStyle(fontSize: 13)), subtitle: const Text('Overrides unsafe drive commands', style: TextStyle(fontSize: 10)), value: telemetry.collisionAvoidance, onChanged: telemetry.connected ? onCollision : null),
      const SizedBox(height: 4),
      Expanded(child: ListView(children: telemetry.motors.map((m) => Padding(padding: const EdgeInsets.only(bottom: 7), child: Row(children: [
        Expanded(child: Text(m.id, style: const TextStyle(fontSize: 11, color: Color(0xFFAAB7C5)))),
        Text('${m.temperatureC.toStringAsFixed(0)}°C', style: TextStyle(fontSize: 11, color: m.temperatureC < 70 ? const Color(0xFF63E67D) : Colors.orange)),
        const SizedBox(width: 9),
        SizedBox(width: 44, child: Text('${m.currentA.toStringAsFixed(1)}A', textAlign: TextAlign.right, style: const TextStyle(fontSize: 11))),
      ]))).toList())),
      FilledButton.icon(onPressed: busy || !telemetry.connected || telemetry.estop ? null : onArm, icon: Icon(telemetry.armed ? Icons.lock : Icons.power_settings_new), label: Text(telemetry.armed ? 'DISARM COUCH' : 'ARM COUCH')),
      const SizedBox(height: 9),
      OutlinedButton.icon(
        style: OutlinedButton.styleFrom(foregroundColor: telemetry.estop ? const Color(0xFFFFC35A) : const Color(0xFFFF5A5A), side: BorderSide(color: telemetry.estop ? const Color(0xFFFFC35A) : const Color(0xFFFF4545)), padding: const EdgeInsets.symmetric(vertical: 14)),
        onPressed: telemetry.connected ? (telemetry.estop ? onClearEstop : onEstop) : null,
        icon: Icon(telemetry.estop ? Icons.restart_alt : Icons.warning_amber_rounded),
        label: Text(telemetry.estop ? 'CLEAR E-STOP' : 'EMERGENCY STOP'),
      ),
    ]),
  );

  Widget _status(IconData icon, String label, String value, {bool good = true}) => Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Row(children: [
    Icon(icon, size: 18, color: good ? const Color(0xFF36B9FF) : Colors.orange), const SizedBox(width: 8), Expanded(child: Text(label, style: const TextStyle(fontSize: 12, color: Color(0xFF91A1B5)))), Text(value, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
  ]));
}
