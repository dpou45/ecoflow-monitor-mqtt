import requests
import hmac
import hashlib
import time
import json
import ssl
import random
import paho.mqtt.client as mqtt
import os
from tuyapy import TuyaApi
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

# 🔌 Tuya Smart Socket Config
TUYA_USERNAME = os.environ["TUYA_USERNAME"]
TUYA_PASSWORD = os.environ["TUYA_PASSWORD"]
TUYA_COUNTRY_CODE = os.environ.get("TUYA_COUNTRY_CODE", "1")
TUYA_APPLICATION = os.environ.get("TUYA_APPLICATION", "smart_life")
SOCKET_NAME = os.environ.get("SOCKET_NAME", "EcoFlow Smart Socket")  # Nombre en app Tuya

# 🤖 Telegram Config
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ⚡ Configuración de Control
BATTERY_THRESHOLD = 27  # 27%
POWER_THRESHOLD = 100   # 100 watts
SCHEDULE_START = "08:00"  # Hora de inicio
SCHEDULE_END = "14:00"    # Hora de fin

# Variables globales
current_status = {
    "soc_percent": 0,
    "watts_out": 0,
    "socket_state": False,
    "override_active": False
}

class EcoFlowTuyaController:
    def __init__(self):
        # Inicializar Tuya
        self.tuya_api = TuyaApi()
        self.tuya_api.init(TUYA_USERNAME, TUYA_PASSWORD, TUYA_COUNTRY_CODE, TUYA_APPLICATION)
        
        # Inicializar Telegram
        self.telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        # Estado del sistema
        self.socket_device = None
        self._discover_socket()
        
    def _discover_socket(self):
        """Descubrir el socket Tuya"""
        try:
            devices = self.tuya_api.get_all_devices()
            for device in devices:
                if device.name() == SOCKET_NAME:
                    self.socket_device = device
                    print(f"✅ Socket encontrado: {SOCKET_NAME}")
                    return
            
            print(f"❌ Socket '{SOCKET_NAME}' no encontrado")
            print("Dispositivos disponibles:")
            for device in devices:
                print(f"  - {device.name()}")
                
        except Exception as e:
            print(f"❌ Error descubriendo dispositivos Tuya: {e}")
    
    def get_socket_state(self):
        """Obtener estado actual del socket"""
        if self.socket_device:
            try:
                return self.socket_device.state()
            except Exception as e:
                print(f"Error obteniendo estado del socket: {e}")
        return False
    
    def turn_on_socket(self):
        """Encender el socket"""
        if self.socket_device:
            try:
                self.socket_device.turn_on()
                current_status["socket_state"] = True
                print("✅ Socket ENCENDIDO")
                self.send_telegram_alert("🔌 Socket ENCENDIDO")
                return True
            except Exception as e:
                print(f"❌ Error encendiendo socket: {e}")
        return False
    
    def turn_off_socket(self):
        """Apagar el socket"""
        if self.socket_device:
            try:
                self.socket_device.turn_off()
                current_status["socket_state"] = False
                print("🔴 Socket APAGADO")
                self.send_telegram_alert("🔴 Socket APAGADO")
                return True
            except Exception as e:
                print(f"❌ Error apagando socket: {e}")
        return False
    
    def send_telegram_alert(self, message):
        """Enviar alerta por Telegram"""
        try:
            full_message = f"🔋 EcoFlow Alert\n{message}\nBatería: {current_status['soc_percent']}%\nConsumo: {current_status['watts_out']}W\nHora: {datetime.now().strftime('%H:%M:%S')}"
            self.telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=full_message)
            print(f"📱 Telegram alert sent: {message}")
        except TelegramError as e:
            print(f"❌ Error enviando Telegram: {e}")
    
    def check_conditions(self, soc_percent, watts_out):
        """Verificar condiciones para control automático"""
        global current_status
        
        current_status["soc_percent"] = soc_percent
        current_status["watts_out"] = watts_out
        
        # Verificar si estamos en el horario programado
        current_time = datetime.now().time()
        start_time = dt_time(8, 0)   # 08:00
        end_time = dt_time(14, 0)    # 14:00
        
        in_schedule_time = start_time <= current_time <= end_time
        
        # Condiciones de override
        battery_low = soc_percent < BATTERY_THRESHOLD
        power_low = watts_out < POWER_THRESHOLD
        
        # Lógica de control
        if in_schedule_time:
            if battery_low or power_low:
                # Condiciones de override - mantener socket encendido
                if not current_status["override_active"]:
                    self.send_telegram_alert(
                        f"🚨 OVERRIDE ACTIVADO\n"
                        f"Batería: {soc_percent}% < {BATTERY_THRESHOLD}% "
                        f"o Consumo: {watts_out}W < {POWER_THRESHOLD}W"
                    )
                    current_status["override_active"] = True
                
                # Asegurar que el socket esté encendido
                if not self.get_socket_state():
                    self.turn_on_socket()
            else:
                # Condiciones normales - apagar socket
                current_status["override_active"] = False
                if self.get_socket_state():
                    self.turn_off_socket()
        else:
            # Fuera del horario - encender socket
            current_status["override_active"] = False
            if not self.get_socket_state():
                self.turn_on_socket()
        
        # Alertas específicas
        if soc_percent < 30:
            self.send_telegram_alert(f"⚠️ Batería CRÍTICA: {soc_percent}%")
        
        if watts_out > 500:  # Alto consumo
            self.send_telegram_alert(f"⚡ Alto consumo: {watts_out}W")

# Funciones existentes de EcoFlow (manteniendo tu código)
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

def run_scheduler():
    """Ejecutar el planificador en segundo plano"""
    while True:
        schedule.run_pending()
        time.sleep(60)

def main():
    # Inicializar controlador
    controller = EcoFlowTuyaController()
    
    # Configurar schedule para verificación periódica
    schedule.every(5).minutes.do(lambda: print("🕒 Schedule check running..."))
    
    # Iniciar scheduler en segundo plano
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Conectar MQTT
    mqtt_client = connect_mqtt()
    
    # Enviar mensaje de inicio
    controller.send_telegram_alert("🚀 Sistema EcoFlow+Tuya INICIADO")
    
    # Bucle principal
    start_time = time.time()
    duration = 5 * 60  # 5 minutos (para Render)
    
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
            
            print(f"🔋 {soc}% | ⚡ {watts_out}W | 💡 Socket: {'ON' if current_status['socket_state'] else 'OFF'} | Override: {current_status['override_active']}")
        
        time.sleep(30)  # Esperar 30 segundos
    
    # Mensaje de finalización
    controller.send_telegram_alert("🛑 Sistema detenido (fin de ciclo Render)")
    mqtt_client.loop_stop()

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
