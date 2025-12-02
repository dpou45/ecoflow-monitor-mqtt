import requests
import hmac
import hashlib
import time
import json
import ssl
import random
import paho.mqtt.client as mqtt
import os
import tinytuya
from datetime import datetime, time as dt_time
import asyncio
from telegram import Bot
from telegram.error import TelegramError

# 🌐 API Config EcoFlow
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
DEVICE_SN = os.environ.get("DEVICE_SN", "")
API_BASE_URL = "https://api.ecoflow.com/iot-open/sign"

# 🐝 HiveMQ Cloud Config
HIVEMQ_BROKER = os.environ.get("HIVEMQ_BROKER", "")
HIVEMQ_PORT = 8883
HIVEMQ_USER = os.environ.get("HIVEMQ_USER", "")
HIVEMQ_PASS = os.environ.get("HIVEMQ_PASS", "")
MQTT_TOPIC = f"ecoflow/{DEVICE_SN}/status"
MQTT_CLIENT_ID = f"ecoflow-{random.randint(1000, 9999)}"

# 🔌 Tuya Cloud API Config
TUYA_ACCESS_ID = os.environ.get("TUYA_ACCESS_ID", "")
TUYA_ACCESS_KEY = os.environ.get("TUYA_ACCESS_KEY", "")
TUYA_DEVICE_ID = os.environ.get("TUYA_DEVICE_ID", "")
TUYA_API_REGION = os.environ.get("TUYA_API_REGION", "us")

# 🤖 Telegram Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ⚡ Configuración de Control
BATTERY_THRESHOLD = 27
POWER_THRESHOLD = 100

def log(message, level="INFO"):
    """Función de logging mejorada"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "ACTION": "🤖",
        "DATA": "📊"
    }
    icon = icons.get(level, "📝")
    print(f"{icon} [{timestamp}] {message}")

class EcoFlowTuyaCloudController:
    def __init__(self):
        log("🚀 Inicializando controlador EcoFlow + Tuya Cloud API", "INFO")
        
        # Verificar credenciales Tuya Cloud
        self.tuya_enabled = all([TUYA_ACCESS_ID, TUYA_ACCESS_KEY, TUYA_DEVICE_ID])
        
        if self.tuya_enabled:
            try:
                # Inicializar Cloud Tuya
                self.cloud = tinytuya.Cloud(
                    apiRegion=TUYA_API_REGION,
                    apiKey=TUYA_ACCESS_ID,
                    apiSecret=TUYA_ACCESS_KEY,
                    apiDeviceID=TUYA_DEVICE_ID
                )
                
                # Testear conexión
                log("🔗 Probando conexión con Tuya Cloud...", "INFO")
                devices = self.cloud.getdevices()
                log(f"✅ Tuya Cloud configurado. {len(devices)} dispositivos disponibles", "SUCCESS")
                
            except Exception as e:
                log(f"❌ Error configurando Tuya Cloud: {str(e)}", "ERROR")
                self.tuya_enabled = False
        else:
            log("⚠️ Credenciales Tuya Cloud incompletas. Modo simulación activado.", "WARNING")
        
        # Configuración Telegram
        self.telegram_enabled = all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID])
        self.telegram_bot = None
        
        if self.telegram_enabled:
            try:
                self.telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
                log("✅ Telegram configurado", "SUCCESS")
            except Exception as e:
                log(f"⚠️ Error configurando Telegram: {e}", "WARNING")
                self.telegram_enabled = False
        
        # Estado del socket
        self.socket_state = False
        self.last_telegram_alert = 0
        self.telegram_cooldown = 300
    
    def get_socket_state(self):
        """Obtener estado actual del socket via Cloud API"""
        if not self.tuya_enabled:
            log("📡 Modo simulación - Estado socket: Simulado", "INFO")
            return self.socket_state
        
        try:
            # Obtener estado del dispositivo via Cloud
            device_status = self.cloud.getstatus(TUYA_DEVICE_ID)
            
            if device_status and 'result' in device_status:
                # Buscar el estado del switch
                for status in device_status['result']:
                    code = status.get('code', '')
                    if code == 'switch_1' or 'switch' in code.lower():
                        self.socket_state = bool(status.get('value', False))
                        log(f"✅ Estado socket ({code}): {'ON' if self.socket_state else 'OFF'}", "SUCCESS")
                        return self.socket_state
            
            return self.socket_state
            
        except Exception as e:
            log(f"❌ Error obteniendo estado via Cloud: {str(e)}", "ERROR")
            return False
    
    def turn_on_socket(self):
        """Encender el socket via Cloud API"""
        if not self.tuya_enabled:
            log("✅ [SIM] Socket ENCENDIDO", "SUCCESS")
            self.socket_state = True
            return True
        
        try:
            # Comando para encender socket
            commands = {
                "commands": [
                    {"code": "switch_1", "value": True}
                ]
            }
            
            result = self.cloud.sendcommand(TUYA_DEVICE_ID, commands)
            
            if result and result.get('success', False):
                self.socket_state = True
                log("✅ Socket ENCENDIDO via Cloud API", "SUCCESS")
                asyncio.run(self._send_telegram_async("🔌 Socket ENCENDIDO"))
                return True
            else:
                log(f"❌ Error en respuesta Cloud: {result}", "ERROR")
                return False
                
        except Exception as e:
            log(f"❌ Error encendiendo socket: {str(e)}", "ERROR")
            return False
    
    def turn_off_socket(self):
        """Apagar el socket via Cloud API"""
        if not self.tuya_enabled:
            log("🔴 [SIM] Socket APAGADO", "SUCCESS")
            self.socket_state = False
            return True
        
        try:
            # Comando para apagar socket
            commands = {
                "commands": [
                    {"code": "switch_1", "value": False}
                ]
            }
            
            result = self.cloud.sendcommand(TUYA_DEVICE_ID, commands)
            
            if result and result.get('success', False):
                self.socket_state = False
                log("🔴 Socket APAGADO via Cloud API", "SUCCESS")
                asyncio.run(self._send_telegram_async("🔴 Socket APAGADO"))
                return True
            else:
                log(f"❌ Error en respuesta Cloud: {result}", "ERROR")
                return False
                
        except Exception as e:
            log(f"❌ Error apagando socket: {str(e)}", "ERROR")
            return False
    
    async def _send_telegram_async(self, message):
        """Enviar mensaje por Telegram (async)"""
        if not self.telegram_enabled or not self.telegram_bot:
            return
        
        current_time = time.time()
        
        # Prevenir spam
        if (current_time - self.last_telegram_alert) < self.telegram_cooldown:
            log(f"📱 Telegram suprimido (anti-spam): {message[:50]}...", "INFO")
            return
        
        try:
            full_message = (
                f"🔋 EcoFlow Alert - Tuya Cloud\n"
                f"{message}\n"
                f"🕒 {datetime.now().strftime('%H:%M:%S')}\n"
                f"📅 {datetime.now().strftime('%d/%m/%Y')}"
            )
            
            await self.telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=full_message)
            self.last_telegram_alert = current_time
            log(f"📱 Telegram enviado: {message}", "SUCCESS")
            
        except Exception as e:
            log(f"❌ Error enviando Telegram: {e}", "ERROR")
    
    def check_conditions(self, soc_percent, watts_out):
        """Verificar condiciones para control automático"""
        current_time = datetime.now().time()
        start_time = dt_time(8, 0)
        end_time = dt_time(14, 0)
        
        in_schedule_time = start_time <= current_time <= end_time
        battery_low = soc_percent < BATTERY_THRESHOLD
        power_low = watts_out < POWER_THRESHOLD
        
        current_state = self.get_socket_state()
        
        log(f"🔍 Verificación condiciones", "INFO")
        log(f"   Hora: {current_time.strftime('%H:%M:%S')}", "DATA")
        log(f"   En horario 08-14h: {'SÍ' if in_schedule_time else 'NO'}", "DATA")
        log(f"   Batería: {soc_percent}% (Umbral: {BATTERY_THRESHOLD}%)", "DATA")
        log(f"   Consumo: {watts_out}W (Umbral: {POWER_THRESHOLD}W)", "DATA")
        log(f"   Estado socket: {'ON' if current_state else 'OFF'}", "DATA")
        
        # LÓGICA DE CONTROL
        if in_schedule_time:
            if battery_low or power_low:
                # Condiciones críticas - mantener encendido
                if not current_state:
                    log("🤖 Acción: ENCENDER - condiciones críticas", "ACTION")
                    self.turn_on_socket()
            else:
                # Condiciones normales - apagar
                if current_state:
                    log("🤖 Acción: APAGAR - horario normal", "ACTION")
                    self.turn_off_socket()
        else:
            # Fuera del horario - encender
            if not current_state:
                log("🤖 Acción: ENCENDER - fuera de horario", "ACTION")
                self.turn_on_socket()

# ============================================================================
# FUNCIONES ECOFLOW API (CORREGIDAS)
# ============================================================================

def hmac_sha256(data, key):
    """Calcular HMAC SHA256"""
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()

def get_query_string(params):
    """Crear query string ordenada"""
    return '&'.join(f"{key}={value}" for key, value in sorted(params.items()))

def make_api_request(url, params=None):
    """Hacer petición a API EcoFlow - CORREGIDA"""
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    
    headers = {
        'accessKey': API_KEY,
        'nonce': nonce,
        'timestamp': timestamp,
        'Content-Type': 'application/json'
    }
    
    # Construir string para firma
    sign_data = ""
    if params:
        sign_data = get_query_string(params) + '&'
    sign_data += get_query_string(headers)
    
    # Generar firma
    headers['sign'] = hmac_sha256(sign_data, API_SECRET)
    
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15
        )
        
        log(f"📡 API Response Status: {response.status_code}", "DATA")
        
        if response.status_code == 200:
            return response.json()
        else:
            log(f"❌ API Error: {response.status_code} - {response.text[:100]}", "ERROR")
            return None
            
    except Exception as e:
        log(f"❌ Error API request: {e}", "ERROR")
        return None

def get_ecoflow_status():
    """Obtener estado de EcoFlow - CORREGIDA"""
    url = f"{API_BASE_URL}/device/quota/all"
    params = {"sn": DEVICE_SN}
    
    log(f"🔗 Consultando API EcoFlow: {DEVICE_SN[:8]}...", "INFO")
    return make_api_request(url, params)

def transform_ecoflow_data(raw_data):
    """Transformar datos de EcoFlow"""
    try:
        if not raw_data or 'data' not in raw_data:
            log("❌ No hay datos en la respuesta", "ERROR")
            return {}
        
        data = raw_data['data']
        return {
            "soc_percent": data.get("pd.soc", 0),
            "watts_in": data.get("pd.wattsInSum", 0),
            "watts_out": data.get("pd.wattsOutSum", 0),
            "battery_temp": data.get("bms_bmsStatus.temp", 0),
            "remaining_time_min": round(data.get("pd.remainTime", 0) / 60, 1),
            "timestamp": datetime.now().isoformat(),
            "device_sn": DEVICE_SN
        }
    except Exception as e:
        log(f"❌ Error transformando datos: {e}", "ERROR")
        log(f"📊 Raw data: {raw_data}", "DATA")
        return {}

# ============================================================================
# MQTT CONFIG (CORREGIDO PARA VERSIÓN ANTIGUA)
# ============================================================================

def setup_mqtt():
    """Configurar cliente MQTT - COMPATIBLE CON VERSIÓN ANTIGUA"""
    try:
        # Usar versión antigua de paho-mqtt
        client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                log("✅ Conectado a HiveMQ", "SUCCESS")
            else:
                log(f"❌ Error conexión MQTT (Código: {rc})", "ERROR")
        
        client.on_connect = on_connect
        client.username_pw_set(HIVEMQ_USER, HIVEMQ_PASS)
        
        # Configurar SSL
        client.tls_set(ca_certs=None, cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(False)
        
        client.connect(HIVEMQ_BROKER, HIVEMQ_PORT, 60)
        client.loop_start()
        return client
        
    except Exception as e:
        log(f"❌ Error configurando MQTT: {e}", "ERROR")
        return None

def publish_mqtt(client, data):
    """Publicar datos a MQTT"""
    if not client:
        return
    
    try:
        payload = json.dumps(data)
        result = client.publish(MQTT_TOPIC, payload, qos=1)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            log(f"📡 MQTT publicado: {data.get('soc_percent', 0)}% batería", "DATA")
        else:
            log(f"⚠️ Error MQTT publish: {result.rc}", "WARNING")
    except Exception as e:
        log(f"❌ Error publicando MQTT: {e}", "ERROR")

# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

async def main_async():
    """Función principal async"""
    log("=" * 70, "INFO")
    log("🚀 SISTEMA DE MONITOREO ECOFLOW + CONTROL TUYA CLOUD", "INFO")
    log("=" * 70, "INFO")
    
    # Verificar variables de entorno críticas
    log("🔍 Verificando configuración...", "INFO")
    
    if not API_KEY or not API_SECRET or not DEVICE_SN:
        log("❌ ERROR: Faltan credenciales EcoFlow", "ERROR")
        log("   Se necesitan: API_KEY, API_SECRET, DEVICE_SN", "ERROR")
        return
    
    log(f"✅ EcoFlow Device: {DEVICE_SN[:8]}...", "SUCCESS")
    log(f"✅ Control Tuya: {'HABILITADO' if all([TUYA_ACCESS_ID, TUYA_ACCESS_KEY, TUYA_DEVICE_ID]) else 'SIMULACIÓN'}", "SUCCESS")
    log(f"✅ Telegram: {'HABILITADO' if TELEGRAM_BOT_TOKEN else 'DESHABILITADO'}", "SUCCESS")
    
    # Inicializar componentes
    controller = EcoFlowTuyaCloudController()
    mqtt_client = setup_mqtt()
    
    # Notificación de inicio
    if controller.telegram_enabled:
        try:
            await controller.telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=(
                    f"🚀 Sistema EcoFlow+Tuya Cloud INICIADO\n"
                    f"🔋 Dispositivo: {DEVICE_SN[:10]}...\n"
                    f"⏰ Horario: 08:00-14:00\n"
                    f"📊 Umbrales: {BATTERY_THRESHOLD}% batería | {POWER_THRESHOLD}W consumo"
                )
            )
            log("✅ Notificación Telegram de inicio enviada", "SUCCESS")
        except Exception as e:
            log(f"❌ Error enviando Telegram de inicio: {e}", "ERROR")
    
    # Bucle principal
    cycle = 0
    max_cycles = 10
    start_time = time.time()
    
    try:
        while cycle < max_cycles:
            cycle += 1
            log(f"\n{'='*40}", "INFO")
            log(f"🔄 CICLO {cycle}/{max_cycles}", "INFO")
            
            # 1. Obtener datos EcoFlow
            raw_data = get_ecoflow_status()
            
            if raw_data:
                data = transform_ecoflow_data(raw_data)
                
                if data:
                    # 2. Publicar a MQTT
                    publish_mqtt(mqtt_client, data)
                    
                    # 3. Aplicar lógica de control
                    soc = data.get("soc_percent", 0)
                    watts = data.get("watts_out", 0)
                    
                    controller.check_conditions(soc, watts)
                    
                    # 4. Mostrar resumen
                    log(f"📊 RESUMEN:", "INFO")
                    log(f"   🔋 Batería: {soc}%", "DATA")
                    log(f"   ⚡ Consumo: {watts}W", "DATA")
                    log(f"   💡 Socket: {'ON' if controller.socket_state else 'OFF'}", "DATA")
                else:
                    log("❌ Datos EcoFlow incompletos", "ERROR")
            else:
                log("❌ No se pudieron obtener datos de EcoFlow", "ERROR")
                log("💡 Verifica:", "INFO")
                log("   • API_KEY y API_SECRET correctos", "INFO")
                log("   • DEVICE_SN correcto", "INFO")
                log("   • Conexión a internet", "INFO")
            
            # Esperar entre ciclos
            if cycle < max_cycles:
                log(f"⏳ Esperando 30 segundos...", "INFO")
                await asyncio.sleep(30)
    
    except KeyboardInterrupt:
        log("\n🛑 Interrupción por usuario", "WARNING")
    except Exception as e:
        log(f"❌ Error en bucle principal: {e}", "ERROR")
        import traceback
        traceback.print_exc()
    finally:
        # Limpieza
        log("\n🧹 Finalizando sistema...", "INFO")
        
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        
        if controller.telegram_enabled:
            duration = time.time() - start_time
            try:
                await controller.telegram_bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=(
                        f"🛑 Sistema detenido\n"
                        f"⏱️  Duración: {duration:.0f}s\n"
                        f"🔄 Ciclos: {cycle}"
                    )
                )
            except Exception as e:
                log(f"❌ Error enviando Telegram final: {e}", "ERROR")
        
        log("=" * 70, "INFO")
        log(f"✅ SISTEMA FINALIZADO", "SUCCESS")
        log(f"   Ciclos: {cycle}", "INFO")
        log(f"   Tiempo: {time.time() - start_time:.1f}s", "INFO")
        log("=" * 70, "INFO")

def main():
    """Punto de entrada"""
    asyncio.run(main_async())

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




