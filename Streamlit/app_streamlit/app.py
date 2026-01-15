import streamlit as st
import json
import queue
import time
import socket
import threading                      # ✅ AJOUT
from collections import deque
import paho.mqtt.client as mqtt
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# -------------------------
# CONFIG PAGE
# -------------------------
st.set_page_config(layout="wide")
st.title("Projet Final: A311 - Industrie 4.0 et A304 - Systèmes Embarqués II (2025 - 2026)")

# -------------------------
# AUTOREFRESH (en ms)
# -------------------------
count = st_autorefresh(interval=3_000, limit=None, key="mqtt_autorefresh")

# -------------------------
# MQTT CONFIG
# -------------------------
MQTT_BROKER = "51.103.178.209"
MQTT_PORT = 1883
MQTT_SUB_TOPIC = "ESP32/Streamlit"
MQTT_PUB_TOPIC = "ESP32/Station 1"
HIST_LEN = 50

# -------------------------
# Fonctions "climat"
# -------------------------
def compute_ressenti(temp):
    if 0 <= temp <= 20:
        return "froid"
    elif 20 < temp <= 25:
        return "doux"
    elif temp > 25:
        return "chaud"

def compute_periode_journee(lum):
    if 0 <= lum <= 20:
        return "Nuit"
    elif 20 < lum <= 50:
        return "Soir"
    elif lum > 50:
        return "Jour"

def compute_temps_quil_fait(temp, hum, lum):
    if temp <= 20 and hum >= 80 and lum <= 50:
        return "Pluvieux"
    if temp > 20 and hum >= 50 and lum >= 50:
        return "Nuageux"
    if temp >= 20 and hum <= 50 and lum > 80:
        return "Ensoleillé"
    if temp <= 0 and 30 <= lum <= 70 and hum >= 80:
        return "Neigeux"
    return "Temps normal"

# -------------------------
# Queue globale MQTT
# -------------------------
if "mqtt_queue" not in st.session_state:
    st.session_state.mqtt_queue = queue.Queue()
mqtt_queue = st.session_state.mqtt_queue

if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

# -------------------------
# INIT valeurs et historiques
# -------------------------
if "temperature" not in st.session_state:
    st.session_state.temperature = None
if "humidity" not in st.session_state:
    st.session_state.humidity = None
if "luminosity" not in st.session_state:
    st.session_state.luminosity = None

if "temp_hist" not in st.session_state:
    st.session_state.temp_hist = deque(maxlen=HIST_LEN)
if "hum_hist" not in st.session_state:
    st.session_state.hum_hist = deque(maxlen=HIST_LEN)
if "lum_hist" not in st.session_state:
    st.session_state.lum_hist = deque(maxlen=HIST_LEN)

# LED default
if "led" not in st.session_state:
    st.session_state.led = False
if "led_r" not in st.session_state:
    st.session_state.led_r = 0
if "led_g" not in st.session_state:
    st.session_state.led_g = 0
if "led_b" not in st.session_state:
    st.session_state.led_b = 0

if "prev_led" not in st.session_state:
    st.session_state.prev_led = st.session_state.led
if "prev_rgb" not in st.session_state:
    st.session_state.prev_rgb = (
        st.session_state.led_r,
        st.session_state.led_g,
        st.session_state.led_b,
    )

if "climat_style_injected" not in st.session_state:
    st.session_state.climat_style_injected = False

# -------------------------
# MQTT callbacks
# -------------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connecté, abonnement au topic:", MQTT_SUB_TOPIC)
        client.subscribe(MQTT_SUB_TOPIC)
    else:
        print("Échec connexion MQTT, code rc =", rc)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        mqtt_queue.put(data)
    except Exception as e:
        print("Erreur on_message:", e)

# ==========================================================
# ✅ THREAD MQTT (REMPLACE loop_start)
# ==========================================================
def mqtt_thread_worker():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        st.session_state.mqtt_client = client
        client.loop_forever()          # ✅ BLOQUANT DANS LE THREAD
    except Exception as e:
        print("Erreur MQTT thread:", e)

if not st.session_state.mqtt_started:
    threading.Thread(
        target=mqtt_thread_worker,
        daemon=True
    ).start()
    st.session_state.mqtt_started = True

# -------------------------
# Traitement de la queue MQTT
# -------------------------
def process_mqtt_queue():
    updated = False
    while not mqtt_queue.empty():
        data = mqtt_queue.get()

        temp = data.get("temperature")
        hum = data.get("humidity")
        lum = data.get("luminosity")

        if temp is not None:
            st.session_state.temperature = float(temp)
            st.session_state.temp_hist.append(st.session_state.temperature)
            updated = True
        if hum is not None:
            st.session_state.humidity = float(hum)
            st.session_state.hum_hist.append(st.session_state.humidity)
            updated = True
        if lum is not None:
            st.session_state.luminosity = float(lum)
            st.session_state.lum_hist.append(st.session_state.luminosity)
            updated = True

        led = data.get("led")
        r = data.get("r")
        g = data.get("g")
        b = data.get("b")

        if led is not None:
            st.session_state.led = bool(int(led)) if str(led).isdigit() else bool(led)
        if r is not None:
            st.session_state.led_r = int(r)
        if g is not None:
            st.session_state.led_g = int(g)
        if b is not None:
            st.session_state.led_b = int(b)

    return updated

process_mqtt_queue()

# -------------------------
# Fonction pour publier une commande
# -------------------------
def publish_command(client, topic, payload_dict):
    if client is None:
        return
    try:
        client.publish(topic, json.dumps(payload_dict), qos=1)
    except Exception as e:
        print("Erreur publish_command:", e)

# -------------------------
# SIDEBAR : contrôle LED
# -------------------------
st.sidebar.header("Contrôle LED")

st.session_state.led = st.sidebar.toggle("LED ON / OFF", value=st.session_state.led, key="ui_led")
st.session_state.led_r = st.sidebar.slider("Rouge", 0, 255, st.session_state.led_r, key="ui_r")
st.session_state.led_g = st.sidebar.slider("Vert", 0, 255, st.session_state.led_g, key="ui_g")
st.session_state.led_b = st.sidebar.slider("Bleu", 0, 255, st.session_state.led_b, key="ui_b")

current_rgb = (st.session_state.led_r, st.session_state.led_g, st.session_state.led_b)

if st.session_state.get("mqtt_client"):
    if (st.session_state.led != st.session_state.prev_led) or (current_rgb != st.session_state.prev_rgb):
        payload = {
            "Synchro": st.session_state.sync,
            "LED": st.session_state.led,
            "R": st.session_state.led_r,
            "G": st.session_state.led_g,
            "B": st.session_state.led_b,
        }
        publish_command(st.session_state.mqtt_client, MQTT_PUB_TOPIC, payload)
        st.session_state.prev_led = st.session_state.led
        st.session_state.prev_rgb = current_rgb

st.sidebar.write("☀️ LED ON" if st.session_state.led else "🌑 LED OFF")

if "sync" not in st.session_state:
    st.session_state.sync = False

if st.sidebar.button("🧭 🔁 Synchro"):
    st.session_state.sync = not st.session_state.sync
    payload = {
        "Synchro": st.session_state.sync,
        "LED": st.session_state.led,
        "R": st.session_state.led_r,
        "G": st.session_state.led_g,
        "B": st.session_state.led_b,
    }
    publish_command(st.session_state.mqtt_client, MQTT_PUB_TOPIC, payload)

st.sidebar.write("🔄 Mode synchronisé" if st.session_state.sync else "🔒 Mode local")

# -------------------------
# MAIN DASHBOARD (UI INCHANGÉE)
# -------------------------
st.header("📡 Station Météo")
st.subheader("Groupe A05")

# -------------------------
# DEBUG
# -------------------------
with st.expander("Debug: dernières valeurs & état MQTT"):
    st.json({
        "temperature": st.session_state.temperature,
        "humidity": st.session_state.humidity,
        "luminosity": st.session_state.luminosity,
        "led": st.session_state.led,
        "led_r": st.session_state.led_r,
        "led_g": st.session_state.led_g,
        "led_b": st.session_state.led_b,
    })
    st.write(f"MQTT client running: {st.session_state.mqtt_started}")
    st.write(f"Broker: {MQTT_BROKER}  Port: {MQTT_PORT}")
    st.write(f"Subscribe topic: {MQTT_SUB_TOPIC}  Publish topic: {MQTT_PUB_TOPIC}")