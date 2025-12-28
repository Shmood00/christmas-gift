from machine import TouchPad, Pin, PWM
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os, gc, json
from ota import OTAUpdater

FILES_TO_UPDATE = [
  "main.py",
  "led_touch.py"
]

# --- 1. CONFIG & GLOBALS ---
def load_config():
    # Helper for hardware-locked decryption
    def _decrypt(data):
        import machine
        key = machine.unique_id()
        return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

    # 1. Try Encrypted File
    if "config.dat" in os.listdir():
        try:
            with open("config.dat", "rb") as f:
                raw_binary = f.read()
            
            # Decrypt and Parse
            decrypted_str = _decrypt(raw_binary).decode('utf-8')
            config_data = json.loads(decrypted_str)
            
            print("[System] Success: Loaded encrypted config.")
            return config_data
        except Exception as e:
            print("[System] Failed to decrypt .dat file:", e)

    # 2. Try Plaintext Fallback (Only for initial setup)
    if "config.json" in os.listdir():
        try:
            with open("config.json", "r") as f:
                print("[System] Loading from plaintext config.json")
                return json.load(f)
        except Exception as e:
            print("[System] Failed to read .json file:", e)

    # 3. Emergency Default (Ensures the rest of the script doesn't crash)
    print("[System] CRITICAL: No config found! Using empty defaults.")
    return {
        "url": "", "user": "", "pass": "", 
        "sub_topics": [], "pub_topic": "touch", 
        "versions": {}, "github_url": ""
    }

# Configuration
CONFIG = load_config()
publish_deadline = 0
mqtt_state = [0] # [pulse_deadline_ticks]
status = {'touch_active': False}
TOPICS = []
VERSION = CONFIG['versions']
GITHUB_URL = CONFIG['github_url']

for topic in CONFIG['sub_topics']:
  TOPICS.append(topic)

async def clear_reset_flag():
    await asyncio.sleep(5)
    try:
        if ".reset_flag" in os.listdir():
            os.remove(".reset_flag")
            print("[System] Stable. Reset flag cleared")
    except Exception as e:
        print("[System] Error clearing flag: ", e)

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

async def on_msg(topic, payload):
    t = topic.decode()
    p = payload.decode()
    print(f"[MQTT] Message received! Topic: {t}, Payload: {p}")
    
    # Simple Reboot Trigger for Updates
    if t == "tree/cmd/update":
        import machine
        print("[System] Reboot command received. Restarting to check for updates...")
        # Give the system a moment to finish any pending tasks
        await asyncio.sleep(0.5)
        machine.reset()

    # Existing logic for extending the pulse deadline
    mqtt_state[0] = time.ticks_add(time.ticks_ms(), 5000)

async def pulse_led(led_pwm):
    phase = 0
    while True:
        await asyncio.sleep_ms(20)
        is_touching = status['touch_active']
        is_mqtt_active = time.ticks_diff(mqtt_state[0], time.ticks_ms()) > 0
        
        if is_touching or is_mqtt_active:
            brightness = int((math.sin(phase)*0.5+0.5)*1023)
            led_pwm.duty(brightness)
            phase += 0.1
        else:
            led_pwm.duty(0)
            phase = 0

async def example():

    try:
      if ".reset_flag" in os.listdir():
        os.remove(".reset_flag")
        print("[System] Stability confirmed. Flag removed")
    except:
      pass
  
    global publish_deadline

    await asyncio.sleep(1)
    gc.collect()
    
    ota = OTAUpdater(GITHUB_URL, FILES_TO_UPDATE)
    update_triggered = ota.check_and_update(CONFIG)

    if update_triggered:
        return

    asyncio.create_task(clear_reset_flag())
      
    # Setup Hardware
    touch_pin = TouchPad(Pin(27))
    leds = Pin(33, Pin.OUT)
    led_pwm = PWM(leds)
    led_pwm.freq(500)

    touch_threshold = await calibrate_touch(touch_pin)
    
    # Initialize MQTT Client with aggressive 30s KeepAlive for Cloudflare
    client = MQTTWebSocketClient(
        CONFIG['url'], 
        username=CONFIG['user'], 
        password=CONFIG['pass'], 
        ssl_params={'cert_reqs': 0},
        keepalive=30 
    )
    client.set_callback(on_msg)

    asyncio.create_task(pulse_led(led_pwm))

    print("[System] Starting Main Loop...")
    loop_count = 0

    while True:
        loop_count += 1
        # 1. Check/Maintain Connection
        if not client._connected:
            try:
                print("[MQTT] Connecting to Cloudflare Tunnel...")
                await client.connect()
                
                # IMPORTANT: You must re-subscribe after every reconnect
                for topic in TOPICS:
                    await client.subscribe(topic)
                print(f"[MQTT] Connected and Subscribed to {TOPICS}")
                gc.collect()
            except Exception as e:
                print(f"[MQTT] Connection failed: {e}. Retrying in 5s...")
                gc.collect()
                await asyncio.sleep(5)
                continue

        # 2. Handle Touch Logic
        try:
            try:
                data = touch_pin.read()
            except ValueError:
                data = 1000
                
            if data < touch_threshold:
                status['touch_active'] = True
                
                # Rate Limit Publishing
                if time.ticks_diff(time.ticks_ms(), publish_deadline) > 0:
                    print(f"[MQTT] Publishing touch event: {data}")
                    await client.publish(CONFIG['pub_topic'], str(data))
                    publish_deadline = time.ticks_add(time.ticks_ms(), 5000)
            else:
                status['touch_active'] = False

        except Exception as e:
            print(f"[MQTT] Loop Error: {e}")
            # If a publish fails, mark as disconnected so the supervisor fixes it
            client._connected = False

        if loop_count % 100 == 0:
          gc.collect()
          loop_count = 0

        await asyncio.sleep_ms(50)

if __name__ == '__main__':
    try:
        gc.threshold(gc.mem_free() //4 + gc.mem_alloc())
        gc.collect()
      
        asyncio.run(example())
    except KeyboardInterrupt:
        print("Stopped by user")
    except Exception as e:
        import machine
        print('Fatal Error:', e)
        machine.reset()
