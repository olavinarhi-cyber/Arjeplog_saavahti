import streamlit as st
import requests
import pandas as pd
import altair as alt
import psycopg2
from datetime import datetime, date
from streamlit_folium import st_folium
import folium

# Haetaan salainen tietokantaosoite Streamlitin asetuksista
DB_URI = st.secrets["db_uri"]

# 1. PILVITIETOKANTAFUNKTIOT (PostgreSQL / Supabase)
def tallenna_toteutunut_data(df_tunnit, lat, lon):
    try:
        # Lisätty sslmode-parametri varmistamaan suojattu yhteys
        conn = psycopg2.connect(DB_URI, sslmode='require')
        cursor = conn.cursor()
        nyt_str = datetime.now().strftime("%Y-%m-%dT%H:00:00")
        riveja_lisatty = 0
        
        for _, row in df_tunnit.iterrows():
            tunti_aika = row["Aika"].strftime("%Y-%m-%dT%H:00:00")
            if tunti_aika < nyt_str:
                cursor.execute("""
                    INSERT INTO toteutunut_saa (aika, lat, lon, lampotila, ilmanpaine, tuuli, sade)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (aika, lat, lon) DO NOTHING
                """, (
                    tunti_aika, round(lat, 4), round(lon, 4),
                    float(row["Lämpötila"]), float(row["Ilmanpaine"]), float(row["Tuuli"]), float(row["Sademäärä"])
                ))
                if cursor.rowcount > 0:
                    riveja_lisatty += 1
        conn.commit()
        cursor.close()
        conn.close()
        return riveja_lisatty
    except Exception as e:
        st.sidebar.error(f"Tietokantavirhe tallennuksessa: {e}")
        return 0

def hae_historia_tietokannasta(lat, lon):
    try:
        # Lisätty sslmode-parametri varmistamaan suojattu yhteys
        conn = psycopg2.connect(DB_URI, sslmode='require')
        query = "SELECT aika, lampotila, ilmanpaine, tuuli, sade FROM toteutunut_saa WHERE lat = %s AND lon = %s"
        df = pd.read_sql_query(query, conn, params=(round(lat, 4), round(lon, 4)))
        conn.close()
        
        if not df.empty:
            df["Aika"] = pd.to_datetime(df["aika"], format='mixed').dt.tz_localize(None)
            df.rename(columns={
                "lampotila": "Lämpötila", "ilmanpaine": "Ilmanpaine",
                "sade": "Sademäärä", "tuuli": "Tuuli"
            }, inplace=True)
            df.drop(columns=["aika"], inplace=True)
            df["Malli"] = "Toteutunut"
        return df
    except Exception as e:
        st.sidebar.error(f"Tietokantavirhe haussa: {e}")
        return pd.DataFrame()

# 2. SOVELLUKSEN ASETUKSET JA KÄYTTÖLIITTYMÄ
st.set_page_config(page_title="Säävahti", layout="wide")
st.title("🎣 Kalastajan Säävahti (Yr.no & Open-Meteo)")

# SIVUPALKKI: Kartta ja Ajankohta
st.sidebar.header("📍 Valitse sijainti kartalta")

# OLETUSKOORDINAATIT (Arjeplog)
default_lat, default_lon = 66.050, 17.880

if "lat" not in st.session_state:
    st.session_state.lat = default_lat
if "lon" not in st.session_state:
    st.session_state.lon = default_lon

m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=8)
folium.Marker([st.session_state.lat, st.session_state.lon], icon=folium.Icon(color="red")).add_to(m)

kartta_data = st_folium(m, width=300, height=300, key="kartta")

if kartta_data and kartta_data.get("last_clicked"):
    uusi_lat = kartta_data["last_clicked"]["lat"]
    uusi_lon = kartta_data["last_clicked"]["lng"]
    if round(uusi_lat, 4) != round(st.session_state.lat, 4) or round(uusi_lon, 4) != round(st.session_state.lon, 4):
        st.session_state.lat = uusi_lat
        st.session_state.lon = uusi_lon
        st.rerun()

valittu_lat = st.session_state.lat
valittu_lon = st.session_state.lon

st.sidebar.write(f"Lat: {valittu_lat:.4f} | Lon: {valittu_lon:.4f}")

st.sidebar.header("🗓️ Valitse ajanjakso")
tanaan = date.today()
alku_pvm = st.sidebar.date_input("Alkupäivä", tanaan)
loppu_pvm = st.sidebar.date_input("Loppupäivä", tanaan + pd.Timedelta(days=7))

# 3. DATAN HAKU
nyt_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
headers = {'User-Agent': 'KalastusSaavahti/1.0 (opiskelu/harrastusprojekti)'}

url_yr = f"https://api.met.no/weatherapi/locationforecast/2.0/complete?lat={valittu_lat:.4f}&lon={valittu_lon:.4f}"
url_om = f"https://api.open-meteo.com/v1/forecast?latitude={valittu_lat:.4f}&longitude={valittu_lon:.4f}&hourly=temperature_2m,surface_pressure,rain,wind_speed_10m&timezone=auto&forecast_days=14&past_days=2"

@st.cache_data(ttl=600)
def hae_data_lahteet(url_y, url_o):
    res_yr = requests.get(url_y, headers=headers)
    res_om = requests.get(url_o)
    return (res_yr.json() if res_yr.status_code == 200 else None, 
            res_om.json() if res_om.status_code == 200 else None)

yr_json, om_json = hae_data_lahteet(url_yr, url_om)

if yr_json and om_json:
    # --- YR.NO PARSINTA ---
    ts_yr = yr_json["properties"]["timeseries"]
    yr_aika, yr_lampo, yr_paine, yr_tuuli, yr_sade = [], [], [], [], []
    for ts in ts_yr:
        yr_aika.append(ts["time"])
        inst = ts["data"]["instant"]["details"]
        yr_lampo.append(inst.get("air_temperature", 0.0))
        yr_paine.append(inst.get("air_pressure_at_sea_level", 1013.25))
        yr_tuuli.append(inst.get("wind_speed", 0.0))
        sade = 0.0
        if "next_1_hours" in ts["data"]: sade = ts["data"]["next_1_hours"]["details"].get("precipitation_amount", 0.0)
        elif "next_6_hours" in ts["data"]: sade = ts["data"]["next_6_hours"]["details"].get("precipitation_amount", 0.0) / 6.0
        yr_sade.append(sade)
        
    df_yr = pd.DataFrame({"Aika": pd.to_datetime(yr_aika, format='mixed'), "Lämpötila": yr_lampo, "Ilmanpaine": yr_paine, "Sademäärä": yr_sade, "Tuuli": yr_tuuli, "Malli": "Yr.no Ennuste"})
    df_yr["Aika"] = df_yr["Aika"].dt.tz_localize(None)
    
    # Tallennetaan pilvitietokantaan toteutuneet
    uusia_tallennettu = tallenna_toteutunut_data(df_yr, valittu_lat, valittu_lon)
    df_yr_tuleva = df_yr[df_yr["Aika"] >= nyt_dt].copy()

    # --- OPEN-METEO PARSINTA ---
    om_h = om_json["hourly"]
    df_om = pd.DataFrame({"Aika": pd.to_datetime(om_h["time"], format='mixed'), "Lämpötila": om_h["temperature_2m"], "Ilmanpaine": om_h["surface_pressure"], "Sademäärä": om_h["rain"], "Tuuli": om_h["wind_speed_10m"], "Malli": "Open-Meteo Ennuste"})
    df_om["Aika"] = df_om["Aika"].dt.tz_localize(None)
    df_om_tuleva = df_om[df_om["Aika"] >= nyt_dt].copy()

    # --- HISTORIA PILVIKANNASTA ---
    df_historia = hae_historia_tietokannasta(valittu_lat, valittu_lon)

    # Yhdistetään kaikki
    listat = [df_yr_tuleva, df_om_tuleva]
    if not df_historia.empty:
        listat.append(df_historia)
    df_kaikki = pd.concat(listat).sort_values("Aika")

    # Metrics yläpalkkiin
    if not df_yr_tuleva.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Ilmanpaine nyt (Yr.no)", f"{df_yr_tuleva.iloc[0]['Ilmanpaine']} hPa")
        col2.metric("Lämpötila nyt", f"{df_yr_tuleva.iloc[0]['Lämpötila']} °C")
        col3.metric("Tuuli nyt", f"{df_yr_tuleva.iloc[0]['Tuuli']} m/s")
        if uusia_tallennettu > 0:
            st.sidebar.success(f"Pilvikantaan tallennettu {uusia_tallennettu} tuntia.")

    st.markdown("---")

    # 4. SUODATUS JA VISUALISOINTI
    alku_dt = pd.to_datetime(alku_pvm)
    loppu_dt = pd.to_datetime(loppu_pvm) + pd.Timedelta(hours=23, minutes=59)
    df_suodatettu = df_kaikki[(df_kaikki["Aika"] >= alku_dt) & (df_kaikki["Aika"] <= loppu_dt)]

    if df_suodatettu.empty:
        st.warning("Valitulle ajalle ei löydy dataa.")
    else:
        st.subheader("📊 Ennustevertailu samassa graafissa")
        st.caption("Yhtenäinen viiva = Toteutunut historia pilvestä | Katkoviivat = Eri säämallien ennusteet")

        def luo_monikuvaaja(data, y_sarake, otsikko, yksikko):
            chart = alt.Chart(data).mark_line(strokeWidth=2).encode(
                x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
                y=alt.Y(f"{y_sarake}:Q", title=f"{otsikko} ({yksikko})", scale=alt.Scale(zero=False)),
                color=alt.Color("Malli:N", title="Datalähde", scale=alt.Scale(
                    domain=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"],
                    range=["#2ca02c", "#1f77b4", "#ff7f0e"]
                )),
                strokeDash=alt.StrokeDash("Malli:N", sort=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"]),
                tooltip=[alt.Tooltip("Aika:T", format="%d.%m. %H:%M"), alt.Tooltip(f"{y_sarake}:Q"), alt.Tooltip("Malli:N")]
            ).properties(height=350).interactive()
            return chart

        st.write("**Ilmanpaineen vertailu**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Ilmanpaine", "Ilmanpaine", "hPa"), use_container_width=True)

        st.write("**Lämpötilan vertailu**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Lämpötila", "Lämpötila", "°C"), use_container_width=True)

        st.write("**Tuulen nopeuden vertailu**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Tuuli", "Tuuli", "m/s"), use_container_width=True)

        st.write("**Sademäärän vertailu (mm/h)**")
        sade_kuvaaja = alt.Chart(df_suodatettu).mark_bar(opacity=0.6).encode(
            x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
            y=alt.Y("Sademäärä:Q", title="Sademäärä (mm)", stack=None),
            color=alt.Color("Malli:N", title="Datalähde"),
            tooltip=[alt.Tooltip("Aika:T", format="%d.%m. %H:%M"), alt.Tooltip("Sademäärä:Q"), alt.Tooltip("Malli:N")]
        ).properties(height=250).interactive()
        st.altair_chart(sade_kuvaaja, use_container_width=True)
else:
    st.error("Datan haku jostain lähteestä epäonnistui.")