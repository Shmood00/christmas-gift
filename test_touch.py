from machine import TouchPad, Pin, PWM
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os, gc, json
import senko, ntptime

def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except:
        # Fallback if file is missing
        return {"url": "", "user": "", "pass": "", "client_id": "default"}

# Configuration
CONFIG = load_config()

URL = CONFIG['url']
USER = CONFIG['user']
PASS = CONFIG['pass']

TOPICS = []

for topic in CONFIG['sub_topics']:
  TOPICS.append(topic)

publish_deadline = 0
mqtt_state = [0] # [pulse_deadline_ticks]
status = {'touch_active': False}

OTA = senko.Senko(
  user="Shmood00",
  repo="christmas-gift",
  branch="main",
  working_dir="",
  files=["test_touch.py"]
)

async def sync_time():
    print("[System] Syncing time via NTP...")
    try:
        ntptime.settime()
        print("[System] Time synced successfully")
    except Exception as e:
        print("[System] Time sync failed:", e)

async def check_for_updates():
    print("[OTA] Checking for updates...")
    try:
        if OTA.update():
            print("[OTA] New version found! Downloading and rebooting...")
            machine.reset()
        else:
            print("[OTA] Code is up to date.")
    except Exception as e:
        print(f"[OTA] Check failed: {e}")

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
    # Added print for debugging
    print(f"[MQTT] Message received! Topic: {topic.decode()}, Payload: {payload.decode()}")
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
    global publish_deadline

    await sync_time()
    await check_for_updates()
    
    asyncio.create_task(clear_reset_flag())
    
    # Setup Hardware
    touch_pin = TouchPad(Pin(27))
    leds = Pin(33, Pin.OUT)
    led_pwm = PWM(leds)
    led_pwm.freq(500)

    touch_threshold = await calibrate_touch(touch_pin)
    
    # Initialize MQTT Client with aggressive 30s KeepAlive for Cloudflare
    client = MQTTWebSocketClient(
        URL, 
        username=USER, 
        password=PASS, 
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
    if ".reset_flag" in os.listdir():
        print("!!! SAFE MODE ACTIVE !!!")
        print("Waiting 15s to allow for manual recovery via USB/Serial...")
        time.sleep(15)
    # -----------------------
    try:
        gc.threshold(gc.mem_free() //4 + gc.mem_alloc())
        gc.collect()
      
        asyncio.run(example())
    except KeyboardInterrupt:
        print("Stopped by user")
    except Exception as e:
        import machine
        print('Fatal Error:', e)
        time.sleep(5) # Brief pause to allow you to read the error
        machine.reset()
