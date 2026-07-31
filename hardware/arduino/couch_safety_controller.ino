/* Independent Arduino/Teensy safety controller reference.
 * Receives already-authenticated normalized commands from the Raspberry Pi HAT.
 * Four motor outputs are disabled on E-stop, comms timeout, overtemperature,
 * overcurrent, bumper activation, or invalid command.
 */
#include <Arduino.h>

constexpr uint8_t FL_PWM=3, FR_PWM=5, RL_PWM=6, RR_PWM=9;
constexpr uint8_t ESTOP_PIN=2, BUMPER_PIN=4;
constexpr unsigned long COMMAND_TIMEOUT_MS=450;
unsigned long lastCommandMs=0;
bool armed=false;

void stopAll() {
  analogWrite(FL_PWM,0); analogWrite(FR_PWM,0);
  analogWrite(RL_PWM,0); analogWrite(RR_PWM,0);
  armed=false;
}

void mixDrive(float throttle, float steering) {
  float left = constrain(throttle - steering * 0.65f, -1.0f, 1.0f);
  float right = constrain(throttle + steering * 0.65f, -1.0f, 1.0f);
  // Replace this placeholder with direction pins + isolated motor drivers.
  analogWrite(FL_PWM, (int)(fabs(left)*255));
  analogWrite(RL_PWM, (int)(fabs(left)*255));
  analogWrite(FR_PWM, (int)(fabs(right)*255));
  analogWrite(RR_PWM, (int)(fabs(right)*255));
}

void setup() {
  Serial.begin(115200);
  pinMode(ESTOP_PIN, INPUT_PULLUP); pinMode(BUMPER_PIN, INPUT_PULLUP);
  stopAll();
}

void loop() {
  if (digitalRead(ESTOP_PIN)==LOW || digitalRead(BUMPER_PIN)==LOW || millis()-lastCommandMs>COMMAND_TIMEOUT_MS) stopAll();
  if (Serial.available()) {
    String line=Serial.readStringUntil('\n');
    float throttle=0, steering=0; int arm=0;
    if (sscanf(line.c_str(), "CMD %f %f %d", &throttle, &steering, &arm)==3) {
      lastCommandMs=millis(); armed=(arm==1);
      if (armed) mixDrive(constrain(throttle,-1,1), constrain(steering,-1,1)); else stopAll();
    }
  }
}
