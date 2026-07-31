import 'dart:async';

import 'package:flutter/material.dart';

import 'services/couchpilot_api.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const CouchPilotApp());
}

class CouchPilotApp extends StatelessWidget {
  const CouchPilotApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'CouchPilot',
        theme: ThemeData.dark(useMaterial3: true).copyWith(
          scaffoldBackgroundColor: const Color(0xFF02060A),
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF00C7FF),
            brightness: Brightness.dark,
          ),
        ),
        home: const CouchPilotDashboard(),
      );
}

class CouchPilotDashboard extends StatefulWidget {
  const CouchPilotDashboard({super.key});

  @override
  State<CouchPilotDashboard> createState() => _CouchPilotDashboardState();
}

class _CouchPilotDashboardState extends State<CouchPilotDashboard> {
  final CouchPilotApi _api = CouchPilotApi();
  Timer? _timer;
  Map<String, dynamic> _telemetry = const {};
  String? _error;
  bool _busy = false;
  bool _autoPlan = false;
  int _samples = 420;
  int _scenarios = 7;
  double _riskTail = .18;
  double _obstacleX = 3.2;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(milliseconds: 600), (_) async {
      if (_autoPlan && !_busy) {
        await _plan();
      } else {
        await _poll();
      }
    });
  }

  Future<void> _poll() async {
    try {
      final data = await _api.telemetry();
      if (mounted) setState(() { _telemetry = data; _error = null; });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _plan() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final data = await _api.planDemo(obstacleX: _obstacleX);
      if (mounted) setState(() { _telemetry = data; _error = null; });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _applyConfig() async {
    setState(() => _busy = true);
    try {
      await _api.configure(samples: _samples, scenarios: _scenarios, riskTail: _riskTail);
      await _plan();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _api.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final control = (_telemetry['control'] as Map?)?.cast<String, dynamic>() ?? const {};
    final confidence = (_telemetry['confidence'] as num?)?.toDouble() ?? 0;
    final collision = (_telemetry['collision_probability'] as num?)?.toDouble() ?? 0;
    final clearance = (_telemetry['min_clearance_m'] as num?)?.toDouble() ?? 0;
    final compute = (_telemetry['compute_ms'] as num?)?.toDouble() ?? 0;
    final path = ((_telemetry['predicted_path'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Offset((e['x_m'] as num).toDouble(), (e['y_m'] as num).toDouble()))
        .toList();

    return Scaffold(
      body: SafeArea(
        child: Container(
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(-.4, -.7),
              radius: 1.5,
              colors: [Color(0xFF0A2233), Color(0xFF02060A)],
            ),
          ),
          child: Column(children: [
            _header(confidence, collision),
            if (_error != null)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(8),
                color: const Color(0xFF5A1717),
                child: Text(_error!, textAlign: TextAlign.center),
              ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(children: [
                  Expanded(
                    flex: 6,
                    child: _PlannerCanvas(
                      path: path,
                      obstacleX: _obstacleX,
                      collisionProbability: collision,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    flex: 4,
                    child: Column(children: [
                      Expanded(child: _statusGrid(control, confidence, collision, clearance, compute)),
                      const SizedBox(height: 12),
                      _controls(),
                    ]),
                  ),
                ]),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _header(double confidence, double collision) => Container(
        height: 74,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        decoration: const BoxDecoration(
          color: Color(0xDD061019),
          border: Border(bottom: BorderSide(color: Color(0xFF17415A))),
        ),
        child: Row(children: [
          const Icon(Icons.auto_awesome_motion, color: Color(0xFF31C8FF), size: 30),
          const SizedBox(width: 12),
          const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('COUCHPILOT', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: 2)),
              Text('RISK-SENSITIVE MPPI + CONTROL BARRIER SHIELD', style: TextStyle(fontSize: 10, color: Color(0xFF31C8FF), letterSpacing: 1.1)),
            ],
          ),
          const Spacer(),
          _pill(Icons.psychology_alt, 'BELIEF ${(confidence * 100).toStringAsFixed(0)}%', confidence > .7),
          const SizedBox(width: 10),
          _pill(Icons.shield_outlined, 'TAIL RISK ${(collision * 100).toStringAsFixed(1)}%', collision < .05),
          const SizedBox(width: 10),
          _pill(Icons.science_outlined, 'SIMULATION ONLY', true),
        ]),
      );

  Widget _pill(IconData icon, String text, bool good) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
        decoration: BoxDecoration(
          color: const Color(0xFF091722),
          borderRadius: BorderRadius.circular(99),
          border: Border.all(color: good ? const Color(0xFF2EBD72) : Colors.orangeAccent),
        ),
        child: Row(children: [
          Icon(icon, size: 15, color: good ? const Color(0xFF66E69A) : Colors.orangeAccent),
          const SizedBox(width: 7),
          Text(text, style: const TextStyle(fontSize: 10, letterSpacing: .8)),
        ]),
      );

  Widget _statusGrid(Map<String, dynamic> control, double confidence, double collision, double clearance, double compute) {
    final accel = (control['acceleration_mps2'] as num?)?.toDouble() ?? 0;
    final yawRate = (control['yaw_rate_rps'] as num?)?.toDouble() ?? 0;
    return GridView.count(
      crossAxisCount: 2,
      childAspectRatio: 1.75,
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      children: [
        _metric('ACCELERATION', '${accel.toStringAsFixed(2)} m/s²', Icons.speed),
        _metric('YAW RATE', '${yawRate.toStringAsFixed(2)} rad/s', Icons.rotate_right),
        _metric('MIN CLEARANCE', '${clearance.toStringAsFixed(2)} m', Icons.social_distance, good: clearance > .8),
        _metric('COLLISION RISK', '${(collision * 100).toStringAsFixed(2)}%', Icons.warning_amber, good: collision < .05),
        _metric('PLANNER BELIEF', '${(confidence * 100).toStringAsFixed(1)}%', Icons.hub, good: confidence > .7),
        _metric('COMPUTE', '${compute.toStringAsFixed(0)} ms', Icons.memory, good: compute < 500),
      ],
    );
  }

  Widget _metric(String label, String value, IconData icon, {bool good = true}) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xC4071119),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: good ? const Color(0xFF1C4964) : Colors.orangeAccent),
        ),
        child: Row(children: [
          Icon(icon, color: good ? const Color(0xFF31C8FF) : Colors.orangeAccent),
          const SizedBox(width: 10),
          Expanded(child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(fontSize: 9, color: Color(0xFF86A0B2), letterSpacing: .9)),
              const SizedBox(height: 4),
              Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            ],
          )),
        ]),
      );

  Widget _controls() => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xD0081119),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFF17415A)),
        ),
        child: Column(children: [
          Row(children: [
            const Text('AUTO REPLAN', style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 1)),
            const Spacer(),
            Switch(value: _autoPlan, onChanged: (v) => setState(() => _autoPlan = v)),
          ]),
          Row(children: [
            Expanded(child: Text('MPPI samples: $_samples')),
            Expanded(child: Slider(
              value: _samples.toDouble(), min: 64, max: 1200, divisions: 71,
              onChanged: (v) => setState(() => _samples = v.round()),
            )),
          ]),
          Row(children: [
            Expanded(child: Text('Uncertainty scenarios: $_scenarios')),
            Expanded(child: Slider(
              value: _scenarios.toDouble(), min: 1, max: 20, divisions: 19,
              onChanged: (v) => setState(() => _scenarios = v.round()),
            )),
          ]),
          Row(children: [
            Expanded(child: Text('CVaR tail: ${(_riskTail * 100).toStringAsFixed(0)}%')),
            Expanded(child: Slider(
              value: _riskTail, min: .05, max: .5, divisions: 18,
              onChanged: (v) => setState(() => _riskTail = v),
            )),
          ]),
          Row(children: [
            Expanded(child: Text('Moving obstacle: ${_obstacleX.toStringAsFixed(1)} m')),
            Expanded(child: Slider(
              value: _obstacleX, min: 1.1, max: 7, divisions: 59,
              onChanged: (v) => setState(() => _obstacleX = v),
            )),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: OutlinedButton.icon(
              onPressed: _busy ? null : _applyConfig,
              icon: const Icon(Icons.tune),
              label: const Text('APPLY MODEL'),
            )),
            const SizedBox(width: 10),
            Expanded(child: FilledButton.icon(
              onPressed: _busy ? null : _plan,
              icon: _busy
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.play_arrow),
              label: const Text('PLAN NOW'),
            )),
          ]),
        ]),
      );
}

class _PlannerCanvas extends StatelessWidget {
  const _PlannerCanvas({required this.path, required this.obstacleX, required this.collisionProbability});
  final List<Offset> path;
  final double obstacleX;
  final double collisionProbability;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: const Color(0xC8040B10),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: const Color(0xFF17415A)),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(18),
          child: CustomPaint(
            painter: _PlannerPainter(path, obstacleX, collisionProbability),
            child: const SizedBox.expand(),
          ),
        ),
      );
}

class _PlannerPainter extends CustomPainter {
  _PlannerPainter(this.path, this.obstacleX, this.collisionProbability);
  final List<Offset> path;
  final double obstacleX;
  final double collisionProbability;

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()..color = const Color(0xFF0D2634)..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 38) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (double y = 0; y < size.height; y += 38) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    Offset map(Offset p) => Offset(55 + p.dx * 85, size.height / 2 - p.dy * 85);
    final route = Paint()
      ..color = const Color(0xFF31C8FF)
      ..strokeWidth = 4
      ..style = PaintingStyle.stroke;
    if (path.length > 1) {
      final routePath = Path()..moveTo(map(path.first).dx, map(path.first).dy);
      for (final p in path.skip(1)) {
        final m = map(p);
        routePath.lineTo(m.dx, m.dy);
      }
      canvas.drawPath(routePath, route);
    }

    final couch = map(const Offset(0, 0));
    canvas.drawRRect(
      RRect.fromRectAndRadius(Rect.fromCenter(center: couch, width: 72, height: 48), const Radius.circular(10)),
      Paint()..color = const Color(0xFF13577A),
    );
    canvas.drawCircle(
      map(Offset(obstacleX, .4)),
      34,
      Paint()..color = collisionProbability > .05 ? const Color(0xD9FF6A3D) : const Color(0xD9FFC247),
    );
    canvas.drawCircle(couch, 88, Paint()..color = const Color(0x2231C8FF));
  }

  @override
  bool shouldRepaint(covariant _PlannerPainter oldDelegate) =>
      oldDelegate.path != path || oldDelegate.obstacleX != obstacleX || oldDelegate.collisionProbability != collisionProbability;
}
