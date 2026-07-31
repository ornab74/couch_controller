class MotorTelemetry {
  const MotorTelemetry({
    required this.id,
    required this.rpm,
    required this.temperatureC,
    required this.currentA,
    required this.output,
  });

  final String id;
  final double rpm;
  final double temperatureC;
  final double currentA;
  final double output;

  factory MotorTelemetry.fromJson(Map<String, dynamic> json) => MotorTelemetry(
        id: json['id'] as String,
        rpm: (json['rpm'] as num).toDouble(),
        temperatureC: (json['temperature_c'] as num).toDouble(),
        currentA: (json['current_a'] as num).toDouble(),
        output: (json['output'] as num).toDouble(),
      );
}

class CouchTelemetry {
  const CouchTelemetry({
    required this.connected,
    required this.armed,
    required this.batteryPercent,
    required this.batteryVoltage,
    required this.speedMph,
    required this.headingDeg,
    required this.collisionAvoidance,
    required this.closestObstacleFt,
    required this.estop,
    required this.motors,
    required this.updatedAt,
  });

  final bool connected;
  final bool armed;
  final double batteryPercent;
  final double batteryVoltage;
  final double speedMph;
  final double headingDeg;
  final bool collisionAvoidance;
  final double closestObstacleFt;
  final bool estop;
  final List<MotorTelemetry> motors;
  final DateTime updatedAt;

  factory CouchTelemetry.fromJson(Map<String, dynamic> json) => CouchTelemetry(
        connected: json['connected'] as bool? ?? true,
        armed: json['armed'] as bool? ?? false,
        batteryPercent: (json['battery_percent'] as num).toDouble(),
        batteryVoltage: (json['battery_voltage'] as num).toDouble(),
        speedMph: (json['speed_mph'] as num).toDouble(),
        headingDeg: (json['heading_deg'] as num).toDouble(),
        collisionAvoidance: json['collision_avoidance'] as bool? ?? true,
        closestObstacleFt: (json['closest_obstacle_ft'] as num).toDouble(),
        estop: json['estop'] as bool? ?? false,
        motors: (json['motors'] as List<dynamic>)
            .map((e) => MotorTelemetry.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? '') ??
            DateTime.now(),
      );

  static CouchTelemetry disconnected() => CouchTelemetry(
        connected: false,
        armed: false,
        batteryPercent: 0,
        batteryVoltage: 0,
        speedMph: 0,
        headingDeg: 0,
        collisionAvoidance: true,
        closestObstacleFt: 0,
        estop: false,
        motors: const [],
        updatedAt: DateTime.now(),
      );
}
