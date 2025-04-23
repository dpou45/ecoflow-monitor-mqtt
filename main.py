import requests
import hmac
import hashlib
import time
import json
import ssl
import random
import paho.mqtt.client as mqtt

# 🌐 API Config
API_KEY = "QBXfwyvG47U3davrKX8OEVqYPzJvUkSE"
API_SECRET = "nal1Mnumix5lpzK4zUFMZUNIm1sNFJmR"
DEVICE_SN = "R611ZAB6XG7J1240"
API_BASE_URL = "https://api.ecoflow.com/iot-open/sign"

# 🐝 HiveMQ Cloud Config
HIVEMQ_BROKER = "c091aaae2df940a39307e76e7998c5e0.s1.eu.hivemq.cloud"
HIVEMQ_PORT = 8883
HIVEMQ_USER = "docana45"
HIVEMQ_PASS = "EliSamu81820"
MQTT_TOPIC = f"ecoflow/{DEVICE_SN}/status"
MQTT_CLIENT_ID = f"ecoflow-render-{random.randint(1000,9999)}"

# 🔗 Make.com webhook (optional)
MAKE_WEBHOOK_URL = "https://hook.us1.make.com/oyy2deqncdptxkl7j4gv6s2yha7eilvv"  # or leave blank if not used

POLL_INTERVAL = 60  # seconds


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
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to HiveMQ")
        else:
            print("Connection failed. Code:", rc)

    client = mqtt.Client(client_id=MQTT_CLIENT_ID, protocol=mqtt.MQTTv311, transport="tcp")
    client.username_pw_set(HIVEMQ_USER, HIVEMQ_PASS)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.connect(HIVEMQ_BROKER, HIVEMQ_PORT, 60)
    client.loop_start()
    return client


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
    while True:
        raw = get_status()
        if raw:
            data = transform_data(raw)
            publish_to_mqtt(mqtt_client, data)
            publish_to_make(data)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()