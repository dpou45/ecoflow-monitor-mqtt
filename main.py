import requests
import hmac
import hashlib
import time
import json
import ssl
import random
import paho.mqtt.client as mqtt
import os

# 🌐 API Config
API_KEY = os.environ["API_KEY"]
API_SECRET = os.environ["API_SECRET"]
DEVICE_SN = os.environ["DEVICE_SN"]
API_BASE_URL = "https://api.ecoflow.com/iot-open/sign" # ECPFLOW API URL

# 🐝 HiveMQ Cloud Config
HIVEMQ_BROKER = os.environ["HIVEMQ_BROKER"]
HIVEMQ_PORT = 8883
HIVEMQ_USER = os.environ["HIVEMQ_USER"]
HIVEMQ_PASS = os.environ["HIVEMQ_PASS"]
MQTT_TOPIC = f"ecoflow/{DEVICE_SN}/status"
MQTT_CLIENT_ID = f"ecoflow-render-{random.randint(1000,9999)}"

# 🔗 Make.com webhook (optional)
MAKE_WEBHOOK_URL = os.environ["MAKE_URL"]  # or leave blank if not used

# POLL_INTERVAL = 180  # seconds en la caso de porder correr permanentemente


def hmac_sha256(data, key):
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()


def get_query_string(params):
    return '&'.join(f"{key}={params[key]}" for key in sorted(params.keys()))


def make_api_request(url, params=None):
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    headers = {
        'accessKey': API_KEY,
        'nonce': nonce,
        'timestamp': timestamp
    }

    sign_data = (get_query_string(params) + '&' if params else '') + get_query_string(headers)
    headers['sign'] = hmac_sha256(sign_data, API_SECRET)

    try:
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    except Exception as e:
        print(f"API error: {e}")
        return None


def get_status():
    url = f"{API_BASE_URL}/device/quota/all"
    params = {"sn": DEVICE_SN}
    return make_api_request(url, params)


def transform_data(raw_data):
    try:
        data = raw_data['data']
        return {
            "soc_percent": data.get("pd.soc", 0),
            "watts_in": data.get("pd.wattsInSum", 0),
            "watts_out": data.get("pd.wattsOutSum", 0),
            "battery_temp": data.get("bms_bmsStatus.temp", 0),
            "remaining_time_min": round(data.get("pd.remainTime", 0) / 60, 1),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"Transform error: {e}")
        return {}


def connect_mqtt():
    # Create client with callback_api_version=2 to use the newer API
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv5,
        transport="tcp",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    
    # Define callbacks using the new API style
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("Connected to HiveMQ")
        else:
            print(f"Connection failed. Code: {rc}")
    
    client.on_connect = on_connect
    client.username_pw_set(HIVEMQ_USER, HIVEMQ_PASS)
    try:
        ca_cert_path = "hivemq_ca.pem"
        client.tls_set(ca_certs=ca_cert_path, cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(False)
        client.connect(HIVEMQ_BROKER, HIVEMQ_PORT, 60)
        client.loop_start()
        return client
    except ssl.SSLError as e:
        print(f"SSL error: {e}")
        return None


def publish_to_mqtt(client, data):
    try:
        payload = json.dumps(data)
        client.publish(MQTT_TOPIC, payload=payload, qos=1)
        print("MQTT published:", payload)
    except Exception as e:
        print(f"MQTT publish error: {e}")


def publish_to_make(data):
    if not MAKE_WEBHOOK_URL:
        return
    try:
        response = requests.post(MAKE_WEBHOOK_URL, json=data, headers={'Content-Type': 'application/json'})
        print("Sent to Make.com:", response.status_code)
    except Exception as e:
        print(f"Make.com error: {e}")

def main():
    mqtt_client = connect_mqtt()
    start_time = time.time()
    duration = 5 * 60  # 5 minutes in seconds
    while time.time() - start_time < duration:
        raw = get_status()
        if raw:
            data = transform_data(raw)
            publish_to_mqtt(mqtt_client, data)

            soc = data.get("soc_percent", 0)
            if soc < 30 or soc == 88:
                publish_to_make(data)

        time.sleep(30)  # Wait 30 seconds before next fetch

    mqtt_client.loop_stop()
#para el caso que se necesite correr indefinidamente
#def main():
    #mqtt_client = connect_mqtt()
    #while True:
        #raw = get_status()
        #if raw:
           # data = transform_data(raw)
           # publish_to_mqtt(mqtt_client, data)
            #publish_to_make(data)
       # time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
