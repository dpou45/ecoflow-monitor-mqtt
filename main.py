import requests
import hmac
import hashlib
import time
import json
import ssl
import random
import paho.mqtt.client as mqtt
import os
import tinytuya  # Alternativa a tuyapy
import schedule
from datetime import datetime, time as dt_time
import threading
from telegram import Bot
from telegram.error import TelegramError

# 🌐 API Config EcoFlow
API_KEY = os.environ["API_KEY"]
API_SECRET = os.environ["API_SECRET"]
DEVICE_SN = os.environ["DEVICE_SN"]
API_BASE_URL = "https://api.ecoflow.com/iot-open/sign"

# 🐝 HiveMQ Cloud Config
HIVEMQ_BROKER = os.environ["HIVEMQ_BROKER"]
HIVEMQ_PORT = 8883
HIVEMQ_USER = os.environ["HIVEMQ_USER"]
HIVEMQ_PASS = os.environ["HIVEMQ_PASS"]
MQTT_TOPIC = f"ecoflow/{DEVICE_SN}/status"
MQTT_CLIENT_ID = f"ecoflow-render-{random.randint(1000,9999)}"

# 🔌 Tuya Smart Socket Config (ECUADOR)
TUYA_DEVICE_ID = os.environ["TUYA_DEVICE_ID"]
TUYA_LOCAL_KEY = os.environ["TUYA_LOCAL_KEY"]
TUYA_DEVICE_IP = os.environ["TUYA_DEVICE_IP"]

# 🤖 Telegram Config
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ⚡ Configuración de Control
BATTERY_THRESHOLD = 27  # 27%
POWER_THRESHOLD = 100   # 100 watts
SCHEDULE_START = "08:00"  # Hora de inicio
SCHEDULE_END = "14:00"    # Hora de fin

class EcoFlowTuyaControllerEC:
    def __init__(self):
        print("🚀 Inicializando controlador con TinyTuya...")
        
        # Configurar dispositivo Tuya
        self.device = tinytuya.OutletDevice(
            dev_id=TUYA_DEVICE_ID,
            address=TUYA_DEVICE_IP, 
            local_key=TUYA_LOCAL_KEY,
            version=3.3
        )
        
        # Inicializar Telegram
        self.telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        # Estado del sistema
        self.socket_state = False
        
    def get_socket_state(self):
        """Obtener estado actual del socket"""
        try:
            data = self.device.status()
            if 'dps' in data:
                # DPS 1 generalmente controla el encendido/apagado
                self.socket_state = bool(data['dps'].get('1', False))
            return self.socket_state
        except Exception as e:
            print(f"⚠️ Error obteniendo estado del socket: {e}")
            return False
    
    def turn_on_socket(self):
        """Encender el socket"""
        try:
            result = self.device.turn_on()
            self.socket_state = True
            print("✅ Socket ENCENDIDO")
            self.send_telegram_alert("🔌 Socket ENCENDIDO")
            return True
        except Exception as e:
            print(f"❌ Error encendiendo socket: {e}")
            return False
    
    def turn_off_socket(self):
        """Apagar el socket"""
        try:
            result = self.device.turn_off()
            self.socket_state = False
            print("🔴 Socket APAGADO")
            self.send_telegram_alert("🔴 Socket APAGADO")
            return True
        except Exception as e:
            print(f"❌ Error apagando socket: {e}")
            return False
    
    def send_telegram_alert(self, message):
        """Enviar alerta por Telegram"""
        try:
            full_message = (
                f"🔋 EcoFlow Alert - Ecuador 🇪🇨\n"
                f"{message}\n"
                f"🕒 Hora: {datetime.now().strftime('%H:%M:%S')}"
            )
            self.telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=full_message)
            print(f"📱 Telegram alert sent: {message[:50]}...")
        except TelegramError as e:
            print(f"❌ Error enviando Telegram: {e}")
    
    def check_conditions(self, soc_percent, watts_out):
        """Verificar condiciones para control automático"""
        # Obtener hora actual
        current_time = datetime.now().time()
        start_time = dt_time(8, 0)   # 08:00
        end_time = dt_time(14, 0)    # 14:00
        
        in_schedule_time = start_time <= current_time <= end_time
        
        # Condiciones de override
        battery_low = soc_percent < BATTERY_THRESHOLD
        power_low = watts_out < POWER_THRESHOLD
        
        current_socket_state = self.get_socket_state()
        
        print(f"\n🔍 Verificando condiciones:")
        print(f"   Hora: {current_time.strftime('%H:%M')}")
        print(f"   Batería: {soc_percent}%")
        print(f"   Consumo: {watts_out}W")
        print(f"   Estado socket: {'ON' if current_socket_state else 'OFF'}")
        
        # Lógica de control
        if in_schedule_time:
            if battery_low or power_low:
                # Condiciones críticas - mantener encendido
                if not current_socket_state:
                    print("   Acción: ENCENDER (condiciones críticas)")
                    self.turn_on_socket()
            else:
                # Condiciones normales - apagar
                if current_socket_state:
                    print("   Acción: APAGAR (horario normal)")
                    self.turn_off_socket()
        else:
            # Fuera de horario - encender
            if not current_socket_state:
                print("   Acción: ENCENDER (fuera de horario)")
                self.turn_on_socket()

# Mantener las funciones originales de EcoFlow MQTT...

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
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv5,
        transport="tcp",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("✅ Connected to HiveMQ")
        else:
            print(f"❌ Connection failed. Code: {rc}")
    
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
        print(f"❌ SSL error: {e}")
        return None

def publish_to_mqtt(client, data):
    try:
        payload = json.dumps(data)
        client.publish(MQTT_TOPIC, payload=payload, qos=1)
        print("📡 MQTT published")
    except Exception as e:
        print(f"❌ MQTT publish error: {e}")

def main():
    print("=" * 50)
    print("🚀 SISTEMA ECOFLOW + TUYA SOCKET - ECUADOR 🇪🇨")
    print("=" * 50)
    
    try:
        # Inicializar controlador
        controller = EcoFlowTuyaControllerEC()
        
        # Conectar MQTT
        mqtt_client = connect_mqtt()
        
        # Enviar mensaje de inicio
        controller.send_telegram_alert("🚀 Sistema EcoFlow+Tuya INICIADO")
        
        # Bucle principal
        start_time = time.time()
        duration = 5 * 60  # 5 minutos para Render
        
        while time.time() - start_time < duration:
            # Obtener datos de EcoFlow
            raw = get_status()
            if raw:
                data = transform_data(raw)
                
                # Publicar a MQTT
                publish_to_mqtt(mqtt_client, data)
                
                # Aplicar lógica de control
                soc = data.get("soc_percent", 0)
                watts_out = data.get("watts_out", 0)
                
                controller.check_conditions(soc, watts_out)
                
                # Mostrar estado
                print(f"📊 Batería: {soc}% | Consumo: {watts_out}W")
                print("-" * 30)
            
            time.sleep(30)  # Esperar 30 segundos
        
        # Mensaje de finalización
        controller.send_telegram_alert("🛑 Sistema detenido (fin de ciclo)")
        if mqtt_client:
            mqtt_client.loop_stop()
        
    except Exception as e:
        print(f"❌ Error crítico: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()


'''
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

'''


