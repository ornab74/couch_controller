# Couch HAT hardware reference

## Recommended split

- **Phone/tablet app:** UI, encrypted credential vault, transport selection.
- **Raspberry Pi Zero 2 W / Pi 4 HAT:** Wi-Fi/cloud API, BLE GATT, USB CDC, packet authentication, telemetry aggregation.
- **Arduino/Teensy safety MCU:** deterministic watchdog, E-stop loop, bumpers, current/temperature limits, contactor and brake control.
- **Motor drivers:** four isolated, correctly rated traction-motor controllers. Never power motors from Pi/Arduino GPIO.

## USB

Expose the HAT as `/dev/ttyACM0`, 115200 8N1, newline-delimited encrypted JSON. Add the Linux user to `dialout`:

```bash
sudo usermod -aG dialout "$USER"
# Log out and back in.
```

## BLE

Advertise service `8d7b0001-32ad-4c59-b7f2-5c60a39d8830` with command characteristic `...0002` and notify characteristic `...0003`. BLE pairing is transport protection only; application packets remain AES-GCM authenticated.

## Provisioning

Generate a unique 32+ byte bootstrap secret per couch. Install it once on the HAT and enter it once in the app. Do not hardcode one shared production key across every couch.

```bash
openssl rand -base64 48
```

## Mandatory physical safety

Use a normally-closed hardware E-stop, contactor, independent watchdog, current sensing, motor temperature sensing, bump strips, wheel encoders, brakes, fuse protection and a low-speed commissioning mode. Test with the drive wheels lifted before occupied operation.
