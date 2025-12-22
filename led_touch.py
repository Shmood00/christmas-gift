from machine import TouchPad, Pin, PWM
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os

publish_deadline = 0

async def clear_reset_flag():
  await asyncio.sleep(5)
  try:
    if ".reset_flag" in os.listdir():
      os.remove(".reset_flag")
      print("[System] Stable. Reset flag cleared")
  except Exception as e:
    print("[System] Error clearing flag: ",e)

async def calibrate_touch(touch_pin, samples=20):
    print("[Touch] Calibrating... do not touch the sensor.")
    total = 0
    for _ in range(samples):
        total += touch_pin.read()
        await asyncio.sleep_ms(50)
    baseline = total // samples
    # Set threshold to 80% of baseline. If baseline is 600, threshold is 480.
    threshold = int(baseline * 0.8)
    print(f"[Touch] Baseline: {baseline}, Threshold set to: {threshold}")
    return threshold

async def example():

    asyncio.create_task(clear_reset_flag())
  
    url = 'wss://sample.domain:443/'
    user = 'sample_user'
    password = 'password'

    touch_pin = TouchPad(Pin(27))
    leds = Pin(33, Pin.OUT)
    
    led_pwm = PWM(leds)
    led_pwm.freq(500)

    touch_threshold = await calibrate_touch(touch_pin)

    client = MQTTWebSocketClient(url, username=user, password=password, ssl_params={'cert_reqs': 0})

    mqtt_state = [0] # [pulse_deadline_ticks]
    
    async def on_msg(topic, payload):
        # Existing logic for extending the pulse deadline
        mqtt_state[0] = time.ticks_add(time.ticks_ms(), 5000)

    client.set_callback(on_msg)

    await client.connect()
    await client.subscribe('test')
    await client.subscribe('new')

    status = {'touch_active': False}

    async def pulse_led():
      phase = 0
      base_brightness = 150  # Steady state brightness (approx 15%)
      max_brightness = 1023  # Maximum pulse brightness
      amplitude = (max_brightness - base_brightness) / 2
      midpoint = base_brightness + amplitude
  
      while True:
          await asyncio.sleep_ms(20)
          
          is_touching = status['touch_active']
          is_mqtt_active = time.ticks_diff(mqtt_state[0], time.ticks_ms()) > 0
          
          if is_touching or is_mqtt_active:
              # Pulses between base_brightness and max_brightness
              brightness = int(midpoint + math.sin(phase) * amplitude)
              led_pwm.duty(brightness)
              phase += 0.1
          else:
              # Constant base brightness when idle
              led_pwm.duty(base_brightness)
              phase = 0

    asyncio.create_task(pulse_led())
    
    while True:
        await asyncio.sleep_ms(50)
        
        # We need access to the publish_deadline variable defined in the outer scope
        global publish_deadline 

        try:
            data = touch_pin.read()
        except ValueError:
            data = 1000
            
        if data < touch_threshold:
            status['touch_active'] = True
            
            # --- NEW: Rate Limit Check ---
            # Check if current time is past the allowed publish deadline
            if time.ticks_diff(time.ticks_ms(), publish_deadline) > 0:
                # 1. Publish the message (Touch event)
                await client.publish('touch_detected', str(data))
                
                # 2. Extend the deadline by 1000ms (1 second)
                publish_deadline = time.ticks_add(time.ticks_ms(), 5000)
            # -----------------------------
            
        else:
            status['touch_active'] = False

if __name__ == '__main__':
    try:
        asyncio.run(example())
    except Exception as e:
        print('Error', e)
