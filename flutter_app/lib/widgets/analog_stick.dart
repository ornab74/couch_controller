import 'dart:math' as math;

import 'package:flutter/material.dart';

class AnalogStick extends StatefulWidget {
  const AnalogStick({
    super.key,
    required this.title,
    required this.subtitle,
    required this.axis,
    required this.onChanged,
    this.enabled = true,
    this.value = 0,
  });

  final String title;
  final String subtitle;
  final Axis axis;
  final ValueChanged<double> onChanged;
  final bool enabled;
  final double value;

  @override
  State<AnalogStick> createState() => _AnalogStickState();
}

class _AnalogStickState extends State<AnalogStick>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse;
  double _value = 0;

  @override
  void initState() {
    super.initState();
    _value = widget.value;
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
  }

  @override
  void didUpdateWidget(covariant AnalogStick oldWidget) {
    super.didUpdateWidget(oldWidget);
    if ((_value - widget.value).abs() > .001 && _value == 0) {
      _value = widget.value;
    }
  }

  void _update(Offset local, Size size) {
    if (!widget.enabled) return;
    final center = Offset(size.width / 2, size.height / 2);
    final delta = local - center;
    final raw = widget.axis == Axis.vertical
        ? -delta.dy / (size.height * .30)
        : delta.dx / (size.width * .30);
    final next = raw.clamp(-1.0, 1.0);
    setState(() => _value = next.abs() < .035 ? 0 : next);
    widget.onChanged(_value);
  }

  void _release() {
    setState(() => _value = 0);
    widget.onChanged(0);
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final accent = widget.enabled
        ? const Color(0xFF38C6FF)
        : const Color(0xFF526272);
    final magnitude = _value.abs();

    return LayoutBuilder(
      builder: (context, box) {
        final size = math.min(box.maxWidth, box.maxHeight - 72);
        final travel = size * .27;
        final dx = widget.axis == Axis.horizontal ? _value * travel : 0.0;
        final dy = widget.axis == Axis.vertical ? -_value * travel : 0.0;
        final percent = (_value * 100).round();

        return Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  widget.title,
                  style: TextStyle(
                    color: accent,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.4,
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: accent.withValues(alpha: .10),
                    borderRadius: BorderRadius.circular(99),
                    border: Border.all(color: accent.withValues(alpha: .25)),
                  ),
                  child: Text(
                    '${percent >= 0 ? '+' : ''}$percent%',
                    style: TextStyle(
                      color: accent,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              widget.subtitle,
              style: const TextStyle(
                color: Color(0xFF91A3B5),
                fontSize: 11,
                letterSpacing: .8,
              ),
            ),
            const SizedBox(height: 8),
            GestureDetector(
              onPanStart: (d) => _update(d.localPosition, Size(size, size)),
              onPanUpdate: (d) => _update(d.localPosition, Size(size, size)),
              onPanEnd: (_) => _release(),
              onPanCancel: _release,
              child: SizedBox(
                width: size,
                height: size,
                child: AnimatedBuilder(
                  animation: _pulse,
                  builder: (context, _) => Stack(
                    alignment: Alignment.center,
                    children: [
                      Container(
                        width: size,
                        height: size,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: const RadialGradient(
                            colors: [Color(0xFF122334), Color(0xFF05090E)],
                          ),
                          border: Border.all(
                            color: accent.withValues(alpha: .55),
                            width: 1.5,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: accent.withValues(
                                alpha: .10 + (.08 * _pulse.value),
                              ),
                              blurRadius: 24,
                              spreadRadius: 1,
                            ),
                          ],
                        ),
                      ),
                      CustomPaint(
                        size: Size(size, size),
                        painter: _StickPainter(
                          color: accent,
                          axis: widget.axis,
                          value: _value,
                        ),
                      ),
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 90),
                        width: size * (.44 + magnitude * .025),
                        height: size * (.44 + magnitude * .025),
                        transform: Matrix4.translationValues(dx, dy, 0),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: const RadialGradient(
                            center: Alignment(-.32, -.32),
                            colors: [Color(0xFF34495E), Color(0xFF0A0F15)],
                          ),
                          border: Border.all(
                            color: accent.withValues(alpha: .6),
                            width: 1.4,
                          ),
                          boxShadow: [
                            const BoxShadow(
                              color: Colors.black,
                              blurRadius: 18,
                              offset: Offset(0, 9),
                            ),
                            BoxShadow(
                              color: accent.withValues(alpha: .12),
                              blurRadius: 16,
                            ),
                          ],
                        ),
                        child: Center(
                          child: Container(
                            width: size * .18,
                            height: size * .18,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: const Color(0xFF070B10),
                              border: Border.all(
                                color: const Color(0xFF405266),
                              ),
                            ),
                          ),
                        ),
                      ),
                      Positioned(
                        top: 10,
                        child: Icon(
                          Icons.keyboard_arrow_up_rounded,
                          color: widget.axis == Axis.vertical
                              ? accent
                              : const Color(0xFF354556),
                        ),
                      ),
                      Positioned(
                        bottom: 10,
                        child: Icon(
                          Icons.keyboard_arrow_down_rounded,
                          color: widget.axis == Axis.vertical
                              ? accent
                              : const Color(0xFF354556),
                        ),
                      ),
                      Positioned(
                        left: 10,
                        child: Icon(
                          Icons.keyboard_arrow_left_rounded,
                          color: widget.axis == Axis.horizontal
                              ? accent
                              : const Color(0xFF354556),
                        ),
                      ),
                      Positioned(
                        right: 10,
                        child: Icon(
                          Icons.keyboard_arrow_right_rounded,
                          color: widget.axis == Axis.horizontal
                              ? accent
                              : const Color(0xFF354556),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _StickPainter extends CustomPainter {
  const _StickPainter({
    required this.color,
    required this.axis,
    required this.value,
  });

  final Color color;
  final Axis axis;
  final double value;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final tickPaint = Paint()..strokeWidth = 1;
    for (var i = 0; i < 64; i++) {
      final angle = i * math.pi * 2 / 64;
      final outer = size.width * .455;
      final inner = outer - (i % 8 == 0 ? 11 : 5);
      tickPaint.color = color.withValues(alpha: i % 8 == 0 ? .72 : .18);
      canvas.drawLine(
        center + Offset(math.cos(angle) * outer, math.sin(angle) * outer),
        center + Offset(math.cos(angle) * inner, math.sin(angle) * inner),
        tickPaint,
      );
    }

    final guide = Paint()
      ..color = color.withValues(alpha: .14)
      ..strokeWidth = 1;
    canvas.drawCircle(center, size.width * .32, guide..style = PaintingStyle.stroke);
    canvas.drawCircle(center, size.width * .16, guide);

    final lanePaint = Paint()
      ..color = color.withValues(alpha: .22)
      ..strokeWidth = 2;
    if (axis == Axis.vertical) {
      canvas.drawLine(
        Offset(center.dx, size.height * .18),
        Offset(center.dx, size.height * .82),
        lanePaint,
      );
    } else {
      canvas.drawLine(
        Offset(size.width * .18, center.dy),
        Offset(size.width * .82, center.dy),
        lanePaint,
      );
    }

    if (value.abs() > .02) {
      final progress = Paint()
        ..color = color
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round;
      final displacement = size.width * .24 * value;
      if (axis == Axis.vertical) {
        canvas.drawLine(
          center,
          Offset(center.dx, center.dy - displacement),
          progress,
        );
      } else {
        canvas.drawLine(
          center,
          Offset(center.dx + displacement, center.dy),
          progress,
        );
      }
    }
  }

  @override
  bool shouldRepaint(covariant _StickPainter oldDelegate) =>
      oldDelegate.color != color ||
      oldDelegate.axis != axis ||
      oldDelegate.value != value;
}
