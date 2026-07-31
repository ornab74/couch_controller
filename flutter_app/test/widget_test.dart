import 'package:couch_controller/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('renders controller title', (tester) async {
    await tester.pumpWidget(const CouchControllerApp());
    expect(find.text('COUCH CONTROLLER'), findsOneWidget);
  });
}
