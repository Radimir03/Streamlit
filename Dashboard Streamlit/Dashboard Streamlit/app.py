# app.py
import streamlit as st
import json
import queue
import time
from collections import deque
import paho.mqtt.client as mqtt
import pandas as pd

# -------------------------
# CONFIG
# -------------------------
st.set_page_config(layout="wide", page_title="Station météo (MQTT)")

# Options
ENABLE_AUTOREFRESH = False  # mettre True seulement si nécessaire
AUTOREFRESH_INTERVAL_MS = 10_000  # si activé, interval raisonnable

MQTT_BROKER = "51.103.178.209"
MQTT_PORT = 1883
MQTT_SUB_TOPIC = "ESP32/Streamlit"
MQTT_PUB_TOPIC = "ESP32/Station 1"
HIST_LEN = 50

# -------------------------
# Fonctions utilitaires
# -------------------------
def compute_ressenti(temp):
    if temp is None:
        return "—"
    try:
        temp = float(temp)
    except Exception:
        return "—"
    if 0 <= temp <= 20:
        return "froid"
    elif 20 < temp <= 25:
        return "doux"
    elif temp > 25:
        return "chaud"
    return "—"

def compute_periode_journee(lum):
    if lum is None:
        return "—"
    try:
        lum = float(lum)
    except Exception:
        return "—"
    if 0 <= lum <= 20:
        return "Nuit"
    elif 20 < lum <= 50:
        return "Soir"
    elif lum > 50:
        return "Jour"
    return "—"

def compute_temps_quil_fait(temp, hum, lum):
    # Défauts
    try:
        t = float(temp) if temp is not None else None
        h = float(hum) if hum is not None else None
        l = float(lum) if lum is not None else None
    except Exception:
        return "Temps normal"

    if t is None or h is None or l is None:
        return "Temps normal"

    # Pluvieux : T <= 20, H >= 80, L <= 50
    if t <= 20 and h >= 80 and l <= 50:
        return "Pluvieux"
    # Nuageux : T > 20, H >= 50, L >= 50
    if t > 20 and h >= 50 and l >= 50:
        return "Nuageux"
    # Ensoleillé : T >= 20, H <= 50, L > 80
    if t >= 20 and h <= 50 and l > 80:
        return "Ensoleillé"
    # Neigeux : T <= 0, 30 <= L <= 70, H >= 80
    if t <= 0 and 30 <= l <= 70 and h >= 80:
        return "Neigeux"
    return "Temps normal"

# -------------------------
# SESSION STATE: initialisation sûre
# -------------------------
if "mqtt_queue" not in st.session_state:
    st.session_state.mqtt_queue = queue.Queue()

if "mqtt_client" not in st.session_state:
    st.session_state.mqtt_client = None
if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

# Valeurs
defaults = {
    "temperature": None,
    "humidity": None,
    "luminosity": None,
    "led": False,
    "led_r": 0,
    "led_g": 0,
    "led_b": 0,
    "temp_hist": deque(maxlen=HIST_LEN),
    "hum_hist": deque(maxlen=HIST_LEN),
    "lum_hist": deque(maxlen=HIST_LEN),
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -------------------------
# MQTT: callback safe -> push into queue
# -------------------------
def on_connect(client, userdata, flags, rc):
    try:
        client.subscribe(MQTT_SUB_TOPIC)
        print(f"MQTT connecté, subscribe {MQTT_SUB_TOPIC}")
    except Exception as e:
        print("Erreur on_connect:", e)

def on_message(client, userdata, msg):
    payload = None
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
    except Exception as e:
        print("MQTT message parse error:", e, "raw:", payload)
        return
    # Pousser le dict dans la queue thread-safe
    try:
        st.session_state.mqtt_queue.put_nowait(data)
    except Exception as e:
        print("Erreur put queue:", e)

def start_mqtt():
    if st.session_state.mqtt_started:
        return
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        st.session_state.mqtt_client = client
        st.session_state.mqtt_started = True
        print("MQTT démarré")
    except Exception as e:
        st.session_state.mqtt_client = None
        st.session_state.mqtt_started = False
        print("Erreur démarrage MQTT:", e)

def stop_mqtt():
    client = st.session_state.get("mqtt_client")
    if client:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception as e:
            print("Erreur stop MQTT:", e)
    st.session_state.mqtt_client = None
    st.session_state.mqtt_started = False

# -------------------------
# UI: Sidebar (toujours même ordre, keys fixes)
# -------------------------
st.sidebar.header("Contrôles")

# MQTT start/stop
col1, col2 = st.sidebar.columns(2)
if col1.button("Démarrer MQTT", key="btn_start_mqtt"):
    start_mqtt()
if col2.button("Arrêter MQTT", key="btn_stop_mqtt"):
    stop_mqtt()

st.sidebar.markdown("---")

# LED controls (toujours créés)
ui_led = st.sidebar.checkbox("LED ON", value=st.session_state.led, key="ui_led_on")
ui_r = st.sidebar.slider("R (0-255)", 0, 255, st.session_state.led_r, key="ui_led_r")
ui_g = st.sidebar.slider("G (0-255)", 0, 255, st.session_state.led_g, key="ui_led_g")
ui_b = st.sidebar.slider("B (0-255)", 0, 255, st.session_state.led_b, key="ui_led_b")

if st.sidebar.button("Envoyer LED", key="btn_send_led"):
    # Publier seulement si client MQTT dispo
    client = st.session_state.get("mqtt_client")
    if client and st.session_state.mqtt_started:
        payload = json.dumps({
            "led": ui_led,
            "led_r": ui_r,
            "led_g": ui_g,
            "led_b": ui_b,
        })
        try:
            client.publish(MQTT_PUB_TOPIC, payload)
            st.sidebar.success("Message publié")
        except Exception as e:
            st.sidebar.error(f"Erreur publish: {e}")
    else:
        st.sidebar.warning("Client MQTT non démarré")

# Synchroniser st.session_state avec widgets (contrôlé)
st.session_state.led = ui_led
st.session_state.led_r = ui_r
st.session_state.led_g = ui_g
st.session_state.led_b = ui_b

st.sidebar.markdown("---")
st.sidebar.write(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
st.sidebar.write(f"Sub: {MQTT_SUB_TOPIC}")
st.sidebar.write(f"Pub: {MQTT_PUB_TOPIC}")

# -------------------------
# Optionnel: autorefresh (désactivé par défaut)
# -------------------------
if ENABLE_AUTOREFRESH:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=AUTOREFRESH_INTERVAL_MS, limit=None, key="auto_refresh_key")
    except Exception as e:
        st.warning("Autorefresh non disponible: " + str(e))

# -------------------------
# Traitement de la queue MQTT (dans le thread principal)
# -------------------------
def process_mqtt_queue():
    q = st.session_state.mqtt_queue
    updated = False
    while not q.empty():
        try:
            data = q.get_nowait()
        except queue.Empty:
            break
        if not isinstance(data, dict):
            continue
        # Validation et assignation prudente
        t = data.get("temperature")
        h = data.get("humidity")
        l = data.get("luminosity")
        try:
            if t is not None:
                t = float(t)
                st.session_state.temperature = t
                st.session_state.temp_hist.append(t)
            if h is not None:
                h = float(h)
                st.session_state.humidity = h
                st.session_state.hum_hist.append(h)
            if l is not None:
                l = float(l)
                st.session_state.luminosity = l
                st.session_state.lum_hist.append(l)
            updated = True
        except Exception as e:
            print("Erreur lors du parsing des valeurs MQTT:", e)
    return updated

process_mqtt_queue()

# -------------------------
# Main page UI (toujours le même ordre)
# -------------------------
st.title("Projet Final: Station Météo (MQTT)")

# Metrics row
c1, c2, c3 = st.columns(3)
c1.metric("Température (°C)", value=st.session_state.temperature if st.session_state.temperature is not None else "—")
c2.metric("Humidité (%)", value=st.session_state.humidity if st.session_state.humidity is not None else "—")
c3.metric("Luminosité (%)", value=st.session_state.luminosity if st.session_state.luminosity is not None else "—")

# Infos calculées
ressenti = compute_ressenti(st.session_state.temperature)
periode = compute_periode_journee(st.session_state.luminosity)
tempsfait = compute_temps_quil_fait(st.session_state.temperature, st.session_state.humidity, st.session_state.luminosity)

st.markdown(f"**Ressenti** : {ressenti}")
st.markdown(f"**Période** : {periode}")
st.markdown(f"**Temps** : {tempsfait}")

# Graphiques : on aligne les historiques (longueur variable)
def deque_to_list(dq):
    return list(dq) if dq is not None else []

temp_list = deque_to_list(st.session_state.temp_hist)
hum_list = deque_to_list(st.session_state.hum_hist)
lum_list = deque_to_list(st.session_state.lum_hist)

# DataFrame pour line_chart : aligner par index (manque de valeurs -> NaN)
max_len = max(len(temp_list), len(hum_list), len(lum_list), 0)
if max_len > 0:
    # remplir à gauche avec None pour aligner tailles
    def pad_left(lst, n):
        return [None] * (n - len(lst)) + lst
    df = pd.DataFrame({
        "Temp (°C)": pad_left(temp_list, max_len),
        "Hum (%)": pad_left(hum_list, max_len),
        "Lum (%)": pad_left(lum_list, max_len),
    })
    st.line_chart(df)
else:
    st.info("Pas encore de données pour le graphique combiné.")

# Historique séparé (facultatif)
with st.expander("Historique (dernier points)"):
    st.write("Temp:", temp_list[-10:])
    st.write("Hum:", hum_list[-10:])
    st.write("Lum:", lum_list[-10:])

# Debug (toujours même contenu)
with st.expander("Debug: état interne"):
    st.json({
        "temperature": st.session_state.temperature,
        "humidity": st.session_state.humidity,
        "luminosity": st.session_state.luminosity,
        "led": st.session_state.led,
        "led_r": st.session_state.led_r,
        "led_g": st.session_state.led_g,
        "led_b": st.session_state.led_b,
        "mqtt_started": st.session_state.mqtt_started,
    })

# -------------------------
# Clean stop on exit (optionnel)
# -------------------------
# Note: Streamlit Cloud va arrêter le processus ; on garde une fonction pour debug local.
def _on_exit():
    stop_mqtt()

# Hook manuel pour arrêter le client (pratique en développement)
if st.button("Stop MQTT proprement (local)", key="btn_local_stop"):
    stop_mqtt()
    st.success("Stop demandé")

# Fin du fichier
