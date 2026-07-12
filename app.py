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
    "Inari (Juutuanjoki)": {"lat": 68.9050, "lon": 27.0080}
}

# FUNKTIO KUUN VAIHEEN SUOMENTAMISEKSI
def suomenna_kuun_vaihe(val):
    if val < 0.04 or val > 0.96: return "🌑 Uusikuu"
    elif 0.21 <= val <= 0.29: return "🌓 Puolikuu (Kasvava)"
    elif 0.46 <= val <= 0.54: return "🌕 Täysikuu"
    elif 0.71 <= val <= 0.79: return "🌗 Puolikuu (Vähenevä)"
    elif 0.04 <= val < 0.21: return "🌒 Kasvava sirppi"
    elif 0.29 < val < 0.46: return "🌔 Kasvava puolikuu"
    elif 0.54 < val < 0.71: return "🌖 Vähenevä puolikuu"
    else: return "🌘 Vähenevä sirppi"

# AURINGON MATEMAATTINEN LASKENTA
def laske_aurinko_paiva(pvm, lat, lon):
    fmt_pvm = datetime.combine(pvm, datetime.min.time())
    paiva_vuodesta = fmt_pvm.timetuple().tm_yday
    deklinaatio = 0.409 * math.sin(2 * math.pi * (paiva_vuodesta - 81) / 365)
    lat_rad = math.radians(lat)
    luku = (math.sin(math.radians(-0.833)) - math.sin(lat_rad) * math.sin(deklinaatio)) / (math.cos(lat_rad) * math.cos(deklinaatio))
    
    if luku <= -1: return "☀️ Yötön yö", "☀️ Ei laske"
    elif luku >= 1: return "🌑 Kaamos", "🌑 Ei nouse"
        
    tuntikulma = math.acos(luku)
    keskipaiva = 12.0 - (lon / 15.0)
    nousu_utc = keskipaiva - math.degrees(tuntikulma) / 15.0
    lasku_utc = keskipaiva + math.degrees(tuntikulma) / 15.0
    aikakorjaus = 2.0 if lat < 67 else 3.0
    
    nousu_tunnit = (nousu_utc + aikakorjaus) % 24
    lasku_tunnit = (lasku_utc + aikakorjaus) % 24
    return f"{int(nousu_tunnit):02d}:{int((nousu_tunnit%1)*60):02d}", f"{int(lasku_tunnit):02d}:{int((lasku_tunnit%1)*60):02d}"

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
                """, (tunti_aika, lat, lon, float(row["Lämpötila"]), float(row["Ilmanpaine"]), float(row["Tuuli"]), float(row["Sademäärä"])))
                if cursor.rowcount > 0: riveja_lisatty += 1
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
            df.rename(columns={"lampotila": "Lämpötila", "ilmanpaine": "Ilmanpaine", "sade": "Sademäärä", "tuuli": "Tuuli"}, inplace=True)
            df.drop(columns=["aika"], inplace=True)
            df["Malli"] = "Toteutunut"
            df["Sadetodennäköisyys"] = 0.0
            df["Tuulen puuska"] = df["Tuuli"]
        return df
    except Exception as e:
        st.sidebar.error(f"Tietokantavirhe haussa: {e}")
        return pd.DataFrame()

# 3. KÄYTTÖLIITTYMÄN ALUSTUS
st.set_page_config(page_title="Kalareissun säävahti", layout="wide")
st.title("🎣 Kalareissun säävahti")

st.sidebar.header("📍 Kohdevalinta")
valittu_paikka = st.sidebar.selectbox("Valitse kohdealue", list(PAIKAT.keys()))
valittu_lat, valittu_lon = PAIKAT[valittu_paikka]["lat"], PAIKAT[valittu_paikka]["lon"]

st.sidebar.write(f"Koordinaatit: {valittu_lat:.4f}, {valittu_lon:.4f}")
m = folium.Map(location=[valittu_lat, valittu_lon], zoom_start=9)
folium.Marker([valittu_lat, valittu_lon], popup=valittu_paikka).add_to(m)
st_folium(m, width=300, height=200, key="kartta", returned_objects=[])

st.sidebar.header("🗓️ Aikavalinta")
tanaan = date.today()
alku_pvm = st.sidebar.date_input("Alkupäivä", tanaan - timedelta(days=2))
loppu_pvm = st.sidebar.date_input("Loppupäivä", tanaan + timedelta(days=7))

# 4. RATAPINTOJEN HAKU
nyt_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
headers = {'User-Agent': 'KalastusSaavahti/1.0 (opiskelu/harrastusprojekti)'}
aikavyohyke = "Europe/Stockholm" if "Arjeplog" in valittu_paikka else "Europe/Helsinki"

url_yr = f"https://api.met.no/weatherapi/locationforecast/2.0/complete?lat={valittu_lat:.4f}&lon={valittu_lon:.4f}"
url_om = f"https://api.open-meteo.com/v1/forecast?latitude={valittu_lat:.4f}&longitude={valittu_lon:.4f}&hourly=temperature_2m,pressure_msl,rain,wind_speed_10m,wind_gusts_10m,precipitation_probability&timezone={aikavyohyke}&forecast_days=14&past_days=7"

@st.cache_data(ttl=600)
def hae_data(url_y, url_o):
    res_yr, res_om = requests.get(url_y, headers=headers), requests.get(url_o)
    return (res_yr.json() if res_yr.status_code == 200 else None, res_om.json() if res_om.status_code == 200 else None)

yr_json, om_json = hae_data(url_yr, url_om)

if yr_json and om_json:
    # --- YR.NO PARSINTA ---
    ts_yr = yr_json["properties"]["timeseries"]
    yr_aika, yr_lampo, yr_paine, yr_tuuli, yr_puuska, yr_sade = [], [], [], [], [], []
    for ts in ts_yr:
        yr_aika.append(ts["time"])
        inst = ts["data"]["instant"]["details"]
        yr_lampo.append(inst.get("air_temperature", 0.0))
        yr_paine.append(inst.get("air_pressure_at_sea_level", 1013.25))
        yr_tuuli.append(inst.get("wind_speed", 0.0))
        yr_puuska.append(inst.get("wind_speed_of_gust", inst.get("wind_speed", 0.0)))
        sade = 0.0
        if "next_1_hours" in ts["data"]: sade = ts["data"]["next_1_hours"]["details"].get("precipitation_amount", 0.0)
        yr_sade.append(sade)
        
    df_yr = pd.DataFrame({"Aika": pd.to_datetime(yr_aika, format='mixed'), "Lämpötila": yr_lampo, "Ilmanpaine": yr_paine, "Sademäärä": yr_sade, "Tuuli": yr_tuuli, "Tuulen puuska": yr_puuska, "Malli": "Yr.no Ennuste", "Sadetodennäköisyys": 0.0})
    df_yr["Aika"] = df_yr["Aika"].dt.tz_localize(None)
    df_yr_tuleva = df_yr[df_yr["Aika"] >= nyt_dt].copy()

    # --- OPEN-METEO PARSINTA ---
    om_h = om_json["hourly"]
    df_om_kaikki = pd.DataFrame({
        "Aika": pd.to_datetime(om_h["time"], format='mixed'), "Lämpötila": om_h["temperature_2m"], "Ilmanpaine": om_h["pressure_msl"],
        "Sademäärä": om_h["rain"], "Tuuli": om_h["wind_speed_10m"], "Tuulen puuska": om_h["wind_gusts_10m"],
        "Sadetodennäköisyys": om_h["precipitation_probability"], "Malli": "Open-Meteo Ennuste"
    })
    df_om_kaikki["Aika"] = df_om_kaikki["Aika"].dt.tz_localize(None)
    
    df_om_menneet = df_om_kaikki[df_om_kaikki["Aika"] < nyt_dt].copy()
    uusia_tallennettu = tallenna_toteutunut_data(df_om_menneet, valittu_paikka)
    df_om_tuleva = df_om_kaikki[df_om_kaikki["Aika"] >= nyt_dt].copy()

    # --- HISTORIA PILVIKANNASTA ---
    df_historia = hae_historia_tietokannasta(valittu_paikka)
    
    # 5. TILANNEHUONE & MOBIILITIIVISTELMÄ
    if not df_yr_tuleva.empty:
        tuntia_sitten = nyt_dt - timedelta(hours=3)
        paine_nyt = df_yr_tuleva.iloc[0]['Ilmanpaine']
        df_paine_hist = df_historia[df_historia["Aika"] == tuntia_sitten]
        paine_suunta = "— tasainen"
        if not df_paine_hist.empty:
            vanha_paine = df_paine_hist.iloc[0]['Ilmanpaine']
            if paine_nyt > vanha_paine + 0.5: paine_suunta = "↗ NOUSEVA (Keli paranee)"
            elif paine_nyt < vanha_paine - 0.5: paine_suunta = "↘ LASKEVA (Kala aktivoituu)"

        st.markdown("### ⚡ Tilannehuone juuri nyt")
        c1, c2, c3 = st.columns(3)
        c1.metric("Lämpötila", f"{df_yr_tuleva.iloc[0]['Lämpötila']} °C", f"Sade: {df_yr_tuleva.iloc[0]['Sademäärä']} mm/h", delta_color="inverse")
        c2.metric("Ilmanpaine", f"{paine_nyt:.1f} hPa", paine_suunta)
        
        keski_t = df_yr_tuleva.iloc[0]['Tuuli']
        puuska_t = df_yr_tuleva.iloc[0]['Tuulen puuska']
        tuuli_varoitus = "Normaali" if puuska_t < 9 else ("⚠️ Puuskainen" if puuska_t < 13 else "❌ ERITTÄIN KOVA TUULI")
        c3.metric("Tuuli (Puuska)", f"{keski_t:.1f} ({puuska_t:.1f}) m/s", tuuli_varoitus, delta_color="inverse" if puuska_t >= 9 else "normal")

        # MOBIILITIIVISTELMÄ TUULESTA (Poistettu kanoottiviittaukset)
        kovat_tuulet = df_yr_tuleva[df_yr_tuleva["Tuulen puuska"] >= 9.0].head(5)
        if not kovat_tuulet.empty:
            with st.expander("⚠️ **Mobiilivaroitus: Tulevat kovat tuulipuuskat (yli 9 m/s)**"):
                st.caption("Katso tästä kriittiset ajat suojan etsimiseen:")
                for _, kt in kovat_tuulet.iterrows():
                    st.write(f"• **{kt['Aika'].strftime('%d.%m. klo %H:%M')}**: Puuska **{kt['Tuulen puuska']:.1f} m/s** ({kt['Malli']})")

    st.markdown("---")

    # 6. SUODATUS JA VALINTANAPIT
    alku_dt, loppu_dt = pd.to_datetime(alku_pvm), pd.to_datetime(loppu_pvm) + pd.Timedelta(hours=23, minutes=59)
    listat = [df_yr_tuleva, df_om_tuleva]
    if not df_historia.empty: listat.append(df_historia)
    df_kaikki = pd.concat(listat).sort_values("Aika")
    df_suodatettu_pohja = df_kaikki[(df_kaikki["Aika"] >= alku_dt) & (df_kaikki["Aika"] <= loppu_dt)]

    st.markdown("### ⚙️ Graafien hallinta")
    val_col1, val_col2 = st.columns(2)
    
    with val_col1:
        valittu_malli = st.radio(
            "Näytettävä säädata:", 
            ["Kaikki (Vertailu)", "Vain Yr.no", "Vain Open-Meteo"], 
            horizontal=True
        )
    with val_col2:
        yhdistamisen_tila = st.radio(
            "Näkymätyyppi:", 
            ["Erilliset kuvaajat", "Yhdistä Lämpö & Paine"], 
            horizontal=True
        )

    # Suodatetaan data valinnan mukaan
    if valittu_malli == "Vain Yr.no":
        df_suodatettu = df_suodatettu_pohja[df_suodatettu_pohja["Malli"].isin(["Toteutunut", "Yr.no Ennuste"])]
    elif valittu_malli == "Vain Open-Meteo":
        df_suodatettu = df_suodatettu_pohja[df_suodatettu_pohja["Malli"].isin(["Toteutunut", "Open-Meteo Ennuste"])]
    else:
        df_suodatettu = df_suodatettu_pohja

    if df_suodatettu.empty:
        st.warning("Valitulle ajalle ei vielä löydy sääennustetta (Sääennusteet yltävät 14 päivää eteenpäin).")
    else:
        st.subheader(f"📊 Sääkuvaajat: {valittu_paikka}")
        
        # Apufunktio siistien graafien piirtoon ilman mobiilijumiutumista
        def luo_erotettu_graafi(data, y_sarake, otsikko, yksikko):
            chart = alt.Chart(data).mark_line(strokeWidth=2).encode(
                x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
                y=alt.Y(f"{y_sarake}:Q", title=f"{otsikko} ({yksikko})", scale=alt.Scale(zero=False)),
                color=alt.Color("Malli:N", title="Datalähde", scale=alt.Scale(
                    domain=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"],
                    range=["#2ca02c", "#1f77b4", "#ff7f0e"]
                )),
                strokeDash=alt.StrokeDash("Malli:N", sort=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"]),
                tooltip=[alt.Tooltip("Aika:T", format="%d.%m. %H:%M"), alt.Tooltip(f"{y_sarake}:Q"), alt.Tooltip("Malli:N")]
            ).properties(height=200).interactive(bind_y=False)
            return chart

        # TOTEUTETAAN JOKO YHDISTETTY TAI ERILLISET KUVAAT
        if yhdistamisen_tila == "Yhdistä Lämpö & Paine":
            st.write("**Ilmanpaineen ja Lämpötilan yhteiskuvaaja**")
            pohja = alt.Chart(df_suodatettu).encode(x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)))
            
            linja_paine = pohja.mark_line(strokeWidth=2).encode(
                y=alt.Y("Ilmanpaine:Q", title="Ilmanpaine (hPa)", scale=alt.Scale(zero=False)),
                color=alt.Color("Malli:N", scale=alt.Scale(domain=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"], range=["#2ca02c", "#1f77b4", "#ff7f0e"])),
                tooltip=[alt.Tooltip("Aika:T"), alt.Tooltip("Ilmanpaine:Q")]
            )
            linja_lampo = pohja.mark_line(strokeWidth=1.5, strokeDash=[4, 3]).encode(
                y=alt.Y("Lämpötila:Q", title="Lämpötila (°C)", scale=alt.Scale(zero=False)),
                color=alt.Color("Malli:N"),
                tooltip=[alt.Tooltip("Aika:T"), alt.Tooltip("Lämpötila:Q")]
            )
            st.altair_chart(alt.layer(linja_paine, linja_lampo).resolve_scale(y='independent').properties(height=240).interactive(bind_y=False), use_container_width=True)
            st.caption("💡 Yhtenäinen viiva = Ilmanpaine (vasen akseli) | Katkoviiva = Lämpötila (oikea akseli)")
        else:
            st.write("**Ilmanpaineen kehitys**")
            st.altair_chart(luo_erotettu_graafi(df_suodatettu, "Ilmanpaine", "Ilmanpaine", "hPa"), use_container_width=True)
            st.write("**Lämpötilan kehitys**")
            st.altair_chart(luo_erotettu_graafi(df_suodatettu, "Lämpötila", "Lämpötila", "°C"), use_container_width=True)

        # HAALEAT VYÖHYKKEET TUULELLE (Poistettu kanoottitekstit)
        taustavyohykkeet = pd.DataFrame([
            {"aloitus": 0, "lopetus": 9, "Väri": "Kohtuullinen tuuli (0-9 m/s)"},
            {"aloitus": 9, "lopetus": 13, "Väri": "Kova tuuli / Puuskat (9-13 m/s)"},
            {"aloitus": 13, "lopetus": 25, "Väri": "Erittäin kova tuuli (>13 m/s)"}
        ])
        taustavari_kartta = alt.Chart(taustavyohykkeet).mark_rect(opacity=0.06).encode(
            y=alt.Y('aloitus:Q', scale=alt.Scale(domain=[0, 20]), title="m/s"), y2='lopetus:Q',
            color=alt.Color('Väri:N', title="Tuulitilanne", scale=alt.Scale(domain=["Kohtuullinen tuuli (0-9 m/s)", "Kova tuuli / Puuskat (9-13 m/s)", "Erittäin kova tuuli (>13 m/s)"], range=["green", "orange", "red"]))
        )

        st.write("**💨 Keskituulen nopeus**")
        keski_chart = alt.Chart(df_suodatettu).mark_line(strokeWidth=2).encode(
            x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
            y=alt.Y("Tuuli:Q", title="Keskituuli (m/s)", scale=alt.Scale(domain=[0, 20])),
            color=alt.Color("Malli:N", scale=alt.Scale(domain=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"], range=["#2ca02c", "#1f77b4", "#ff7f0e"])),
            strokeDash=alt.StrokeDash("Malli:N"), tooltip=[alt.Tooltip("Aika:T"), alt.Tooltip("Tuuli:Q")]
        ).properties(height=180).interactive(bind_y=False)
        st.altair_chart(alt.layer(taustavari_kartta, keski_chart), use_container_width=True)

        st.write("**🌪️ Tuulen puuskat**")
        puuska_chart = alt.Chart(df_suodatettu).mark_line(strokeWidth=2).encode(
            x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
            y=alt.Y("Tuulen puuska:Q", title="Puuska (m/s)", scale=alt.Scale(domain=[0, 20])),
            color=alt.Color("Malli:N", scale=alt.Scale(domain=["Toteutunut", "Yr.no Ennuste", "Open-Meteo Ennuste"], range=["#2ca02c", "#1f77b4", "#ff7f0e"])),
            strokeDash=alt.StrokeDash("Malli:N"), tooltip=[alt.Tooltip("Aika:T"), alt.Tooltip("Tuulen puuska:Q")]
        ).properties(height=180).interactive(bind_y=False)
        st.altair_chart(alt.layer(taustavari_kartta, puuska_chart), use_container_width=True)

        st.write("**🌧️ Sademäärä (mm/h) & Sadeprosentti**")
        sade_kuvaaja = alt.Chart(df_suodatettu).mark_bar(opacity=0.6).encode(
            x=alt.X("Aika:T", title="Aika", axis=alt.Axis(format="%d.%m. klo %H:%M", labelAngle=-45)),
            y=alt.Y("Sademäärä:Q", title="Sademäärä (mm)", stack=None, scale=alt.Scale(type="sqrt")),
            color=alt.Color("Malli:N", title="Datalähde"),
            tooltip=[alt.Tooltip("Aika:T", format="%d.%m. %H:%M"), alt.Tooltip("Sademäärä:Q", title="Sade (mm)"), alt.Tooltip("Sadetodennäköisyys:Q", title="Todennäköisyys (%)")]
        ).properties(height=150).interactive(bind_y=False)
        st.altair_chart(sade_kuvaaja, use_container_width=True)

    # 7. ASTROTAULUKKO
    st.markdown("---")
    st.subheader("🌅 Auringon nousu- ja laskuajat sekä kuun vaiheet")
    astro_lista = []
    nykyinen_pvm = alku_pvm
    while nykyinen_pvm <= loppu_pvm:
        diff = datetime.combine(nykyinen_pvm, datetime.min.time()) - datetime(2000, 1, 6)
        kuu_val = (diff.days % 29.53059) / 29.53059
        nousu_txt, lasku_txt = laske_aurinko_paiva(nykyinen_pvm, valittu_lat, valittu_lon)
        astro_lista.append({"Päivä": nykyinen_pvm, "Aurinko nousee": nousu_txt, "Aurinko laskee": lasku_txt, "Kuun vaihe": suomenna_kuun_vaihe(kuu_val)})
        nykyinen_pvm += timedelta(days=1)
        
    df_astro_vapaa = pd.DataFrame(astro_lista)
    if not df_astro_vapaa.empty: st.dataframe(df_astro_vapaa.set_index("Päivä"), use_container_width=True)
else:
    st.error("Säädatan haku epäonnistui rajapinnoista.")