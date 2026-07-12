import streamlit as st
import requests
import pandas as pd
import altair as alt
import psycopg2
import math
from datetime import datetime, date, timedelta
from streamlit_folium import st_folium
import folium

# Haetaan salainen tietokantaosoite Streamlitin asetuksista
DB_URI = st.secrets["db_uri"]

# 1. MÄÄRITELLÄÄN KIINTEÄT SÄÄASEMAT / KALAPAIKAT
PAIKAT = {
    "Miekak (Arjeplog)": {"lat": 66.7630, "lon": 17.2340},
    "Inari (Juutuanjoki)": {"lat": 68.9050, "lon": 27.0080},
    "Päivärinne (Muhos)":{"lat":64.8842,"lon":25.8628},
    "Rovaniemi, (keskusta)":{"lat":66.5054,"lon":25.7285}
}

# FUNKTIO KUUN VAIHEEN SUOMENTAMISEKSI
def suomenna_kuun_vaihe(val):
    if val == 0 or val == 1: return "🌑 Uusikuu"
    elif 0 < val < 0.25: return "🌒 Kasvava sirppi"
    elif val == 0.25: return "🌓 Ensimmäinen neljännes"
    elif 0.25 < val < 0.5: return "🌔 Kasvava puolikuu"
    elif val == 0.5: return "🌕 Täysikuu"
    elif 0.5 < val < 0.75: return "🌖 Vähenevä puolikuu"
    elif val == 0.75: return "🌗 Viimeinen neljännes"
    else: return "🌘 Vähenevä sirppi"

# MATEMAATTINEN FUNKTIO AURINGON NOUSU- JA LASKUAIKOJEN LASKEMISEEN POHJOISILLE ALUEILLE
def laske_aurinko_paiva(pvm, lat, lon):
    # Lasketaan vuoden päivä (1-365)
    fmt_pvm = datetime.combine(pvm, datetime.min.time())
    paiva_vuodesta = fmt_pvm.timetuple().tm_yday
    
    # Auringon deklinaatio (likimääräinen kaava)
    deklinaatio = 0.409 * math.sin(2 * math.pi * (paiva_vuodesta - 81) / 365)
    
    # Leveysaste radiaaneina
    lat_rad = math.radians(lat)
    
    # Tuntikulma nousulle/laskulle
    # -0.833 astetta on virallinen horisontin ylitys (auringon halkaisija + refraktio)
    luku = (math.sin(math.radians(-0.833)) - math.sin(lat_rad) * math.sin(deklinaatio)) / (math.cos(lat_rad) * math.cos(deklinaatio))
    
    # Huomioidaan yötön yö tai kaamos pohjoisessa
    if luku <= -1:
        return "☀️ Yötön yö", "☀️ Ei laske"
    elif luku >= 1:
        return "🌑 Kaamos", "🌑 Ei nouse"
        
    tuntikulma = math.acos(luku)
    
    # Keskiaurinkoaika (likimääräinen keskipäivä klo 12 ilman aikayhtälöä)
    keskipaiva = 12.0 - (lon / 15.0)
    
    # Nousu- ja laskuajat UTC-ajassa (tuntikulma muutettuna tunneiksi)
    nousu_utc = keskipaiva - math.degrees(tuntikulma) / 15.0
    lasku_utc = keskipaiva + math.degrees(tuntikulma) / 15.0
    
    # Siirretään Ruotsin/Suomen kesäaikaan (+3 Suomi, +2 Ruotsi)
    # Automaattinen arvio kesäajalle heinäkuussa (+2 kohteesta riippuen)
    aikakorjaus = 2.0 if lat < 67 else 3.0 # Karkea arvio Ruotsi vs Suomi aikavyöhykkeille
    
    nousu_tunnit = (nousu_utc + aikakorjaus) % 24
    lasku_tunnit = (lasku_utc + aikakorjaus) % 24
    
    str_nousu = f"{int(nousu_tunnit):02d}:{int((nousu_tunnit%1)*60):02d}"
    str_lasku = f"{int(lasku_tunnit):02d}:{int((lasku_tunnit%1)*60):02d}"
    
    return str_nousu, str_lasku

# 2. PILVITIETOKANTAFUNKTIOT
def tallenna_toteutunut_data(df_tunnit, paikka_nimi):
    try:
        conn = psycopg2.connect(DB_URI, sslmode='require')
        cursor = conn.cursor()
        nyt_str = datetime.now().strftime("%Y-%m-%dT%H:00:00")
        riveja_lisatty = 0
        
        for _, row in df_tunnit.iterrows():
            tunti_aika = row["Aika"].strftime("%Y-%m-%dT%H:00:00")
            if tunti_aika < nyt_str:
                lat = PAIKAT[paikka_nimi]["lat"]
                lon = PAIKAT[paikka_nimi]["lon"]
                
                cursor.execute("""
                    INSERT INTO toteutunut_saa (aika, lat, lon, lampotila, ilmanpaine, tuuli, sade)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (aika, lat, lon) DO NOTHING
                """, (
                    tunti_aika, lat, lon,
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

def hae_historia_tietokannasta(paikka_nimi):
    try:
        conn = psycopg2.connect(DB_URI, sslmode='require')
        lat = PAIKAT[paikka_nimi]["lat"]
        lon = PAIKAT[paikka_nimi]["lon"]
        
        query = "SELECT aika, lampotila, ilmanpaine, tuuli, sade FROM toteutunut_saa WHERE lat = %s AND lon = %s"
        df = pd.read_sql_query(query, conn, params=(lat, lon))
        conn.close()
        
        if not df.empty:
            df["Aika"] = pd.to_datetime(df["aika"], format='mixed').dt.tz_localize(None)
            df.rename(columns={
                "lampotila": "Lämpötila", "ilmanpaine": "Ilmanpaine",
                "sade": "Sademäärä", "tuuli": "Tuuli"
            }, inplace=True)
            df.drop(columns=["aika"], inplace=True)
            df["Malli"] = "Toteutunut"
            df["Sadetodennäköisyys"] = 0.0
        return df
    except Exception as e:
        st.sidebar.error(f"Tietokantavirhe haussa: {e}")
        return pd.DataFrame()

# 3. SOVELLUKSEN ASETUKSET JA KÄYTTÖLIITTYMÄ
st.set_page_config(page_title="Säävahti", layout="wide")
st.title("🎣 Kalastajan Säävahti (Sääasemaseuranta)")

st.sidebar.header("📍 Valitse seurattava kohde")
valittu_paikka = st.sidebar.selectbox("Kohdealue", list(PAIKAT.keys()))

valittu_lat = PAIKAT[valittu_paikka]["lat"]
valittu_lon = PAIKAT[valittu_paikka]["lon"]

st.sidebar.write(f"**Koordinaatit:** Lat: {valittu_lat} | Lon: {valittu_lon}")

m = folium.Map(location=[valittu_lat, valittu_lon], zoom_start=9)
folium.Marker([valittu_lat, valittu_lon], popup=valittu_paikka, icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)
st_folium(m, width=300, height=250, key="kartta_naytto", returned_objects=[])

st.sidebar.header("🗓️ Valitse ajanjakso graafeille")
tanaan = date.today()
alku_pvm = st.sidebar.date_input("Alkupäivä", tanaan - timedelta(days=2))
loppu_pvm = st.sidebar.date_input("Loppupäivä", tanaan + timedelta(days=20)) # Nyt voi laittaa pitkälle eteenpäin!

# 4. DATAN HAKU
nyt_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
headers = {'User-Agent': 'KalastusSaavahti/1.0 (opiskelu/harrastusprojekti)'}

aikavyohyke = "Europe/Stockholm" if "Arjeplog" in valittu_paikka else "Europe/Helsinki"

url_yr = f"https://api.met.no/weatherapi/locationforecast/2.0/complete?lat={valittu_lat:.4f}&lon={valittu_lon:.4f}"
url_om = f"https://api.open-meteo.com/v1/forecast?latitude={valittu_lat:.4f}&longitude={valittu_lon:.4f}&hourly=temperature_2m,pressure_msl,rain,wind_speed_10m,precipitation_probability&timezone={aikavyohyke}&forecast_days=14&past_days=7"

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
        if "next_1_hours" in ts["data"]: 
            sade = ts["data"]["next_1_hours"]["details"].get("precipitation_amount", 0.0)
        elif "next_6_hours" in ts["data"]: 
            sade = ts["data"]["next_6_hours"]["details"].get("precipitation_amount", 0.0) / 6.0
        yr_sade.append(sade)
        
    df_yr = pd.DataFrame({"Aika": pd.to_datetime(yr_aika, format='mixed'), "Lämpötila": yr_lampo, "Ilmanpaine": yr_paine, "Sademäärä": yr_sade, "Tuuli": yr_tuuli, "Malli": "Yr.no Ennuste", "Sadetodennäköisyys": 0.0})
    df_yr["Aika"] = df_yr["Aika"].dt.tz_localize(None)
    df_yr_tuleva = df_yr[df_yr["Aika"] >= nyt_dt].copy()

    # --- OPEN-METEO PARSINTA ---
    om_h = om_json["hourly"]
    df_om_kaikki = pd.DataFrame({
        "Aika": pd.to_datetime(om_h["time"], format='mixed'), 
        "Lämpötila": om_h["temperature_2m"], 
        "Ilmanpaine": om_h["pressure_msl"], 
        "Sademäärä": om_h["rain"], 
        "Tuuli": om_h["wind_speed_10m"], 
        "Sadetodennäköisyys": om_h["precipitation_probability"],
        "Malli": "Open-Meteo Ennuste"
    })
    df_om_kaikki["Aika"] = df_om_kaikki["Aika"].dt.tz_localize(None)
    
    df_om_menneet = df_om_kaikki[df_om_kaikki["Aika"] < nyt_dt].copy()
    uusia_tallennettu = tallenna_toteutunut_data(df_om_menneet, valittu_paikka)
    df_om_tuleva = df_om_kaikki[df_om_kaikki["Aika"] >= nyt_dt].copy()

    # --- HISTORIA PILVIKANNASTA ---
    df_historia = hae_historia_tietokannasta(valittu_paikka)
    
    st.sidebar.markdown("---")
    st.sidebar.info(f"📊 Tietokannassa yhteensä: {len(df_historia)} tuntihavaintoa paikasta {valittu_paikka}.")
    if uusia_tallennettu > 0:
        st.sidebar.success(f"📥 Lisätty {uusia_tallennettu} uutta tuntia kantaan automaattisesti.")

    listat = [df_yr_tuleva, df_om_tuleva]
    if not df_historia.empty:
        listat.append(df_historia)
    df_kaikki = pd.concat(listat).sort_values("Aika")

    if not df_yr_tuleva.empty:
        col1, col2, col3 = st.columns(3)
        col2.metric(f"Lämpötila nyt ({valittu_paikka})", f"{df_yr_tuleva.iloc[0]['Lämpötila']} °C")
        col1.metric("Ilmanpaine nyt", f"{df_yr_tuleva.iloc[0]['Ilmanpaine']} hPa")
        col3.metric("Tuuli nyt", f"{df_yr_tuleva.iloc[0]['Tuuli']} m/s")

    st.markdown("---")

    # 5. SÄÄDATAN SUODATUS JA VISUALISOINTI
    alku_dt = pd.to_datetime(alku_pvm)
    loppu_dt = pd.to_datetime(loppu_pvm) + pd.Timedelta(hours=23, minutes=59)
    df_suodatettu = df_kaikki[(df_kaikki["Aika"] >= alku_dt) & (df_kaikki["Aika"] <= loppu_dt)]

    if df_suodatettu.empty:
        st.warning("Valitulle ajalle ei vielä löydy sääennustetta (Sääennusteet yltävät 14 päivää eteenpäin).")
    else:
        st.subheader(f"📊 Sääseuranta ja ennusteet: {valittu_paikka}")
        st.caption("VIHREÄ yhtenäinen viiva = Tietokantaan tallennettu aito historia | Katkoviivat = Tulevat ennusteet")

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
            ).properties(height=300).interactive()
            return chart

        st.write("**Ilmanpaineen kehitys**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Ilmanpaine", "Ilmanpaine", "hPa"), use_container_width=True)

        st.write("**Lämpötilan kehitys**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Lämpötila", "Lämpötila", "°C"), use_container_width=True)

        st.write("**Tuulen nopeus**")
        st.altair_chart(luo_monikuvaaja(df_suodatettu, "Tuuli", "Tuuli", "m/s"), use_container_width=True)

        st.write("**Sademäärän vertailu (mm/h) & todennäköisyys**")
        sade_kuvaaja = alt.Chart(df_suodatettu).mark_bar(opacity=0.6).encode(
            x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
            y=alt.Y("Sademäärä:Q", title="Sademäärä (mm)", stack=None, scale=alt.Scale(type="sqrt")),
            color=alt.Color("Malli:N", title="Datalähde"),
            tooltip=[
                alt.Tooltip("Aika:T", format="%d.%m. %H:%M"), 
                alt.Tooltip("Sademäärä:Q", title="Sade (mm)"), 
                alt.Tooltip("Sadetodennäköisyys:Q", title="Todennäköisyys (%)"),
                alt.Tooltip("Malli:N", title="Lähde")
            ]
        ).properties(height=200).interactive()
        st.altair_chart(sade_kuvaaja, use_container_width=True)

    # 6. AURINKO JA KUU -TAULUKKO (Täysin itsenäinen, toimii aina tulevaisuuteen!)
    st.markdown("---")
    st.subheader("🌅 Auringon ja Kuun ajat reissupäiville")
    st.caption("Valitun ajanjakson valoisat ajat sekä kuun vaiheet yön kalastussuunnitelmia varten. (Lasketaan matemaattisesti, toimii mille tahansa päivälle).")
    
    # Luodaan lista valituista päivistä valitulla välillä lennosta
    astro_lista = []
    nykyinen_pvm = alku_pvm
    while nykyinen_pvm <= loppu_pvm:
        # Lasketaan kuun vaihe vapaasti
        diff = datetime.combine(nykyinen_pvm, datetime.min.time()) - datetime(2000, 1, 6)
        kuu_val = (diff.days % 29.53059) / 29.53059
        kuu_txt = suomenna_kuun_vaihe(kuu_val)
        
        # Lasketaan auringon nousut ja laskut matemaattisesti tälle leveysasteelle
        nousu_txt, lasku_txt = laske_aurinko_paiva(nykyinen_pvm, valittu_lat, valittu_lon)
        
        astro_lista.append({
            "Päivä": nykyinen_pvm,
            "Aurinko nousee": nousu_txt,
            "Aurinko laskee": lasku_txt,
            "Kuun vaihe": kuu_txt
        })
        nykyinen_pvm += timedelta(days=1)
        
    df_astro_vapaa = pd.DataFrame(astro_lista)
    
    if not df_astro_vapaa.empty:
        st.dataframe(df_astro_vapaa.set_index("Päivä"), use_container_width=True)
else:
    st.error("Säädatan haku epäonnistui taustalla.")