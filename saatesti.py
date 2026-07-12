import requests
from datetime import datetime

LAT = 66.05
LON = 17.88

# Poistettu moon_phase daily-parametreista virheen takia
url = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LAT}&longitude={LON}"
    f"&hourly=temperature_2m,surface_pressure,rain,wind_speed_10m"
    f"&daily=sunrise,sunset"
    f"&timezone=Europe/Stockholm"
)

print("Haetaan korjattua säädataa Arjeplogista...")
vastaus = requests.get(url)

if vastaus.status_code == 200:
    data = vastaus.json()
    
    # 1. Haetaan tämän hetken tuntia vastaava indeksi
    tuntidata = data["hourly"]
    nyt_tunti = datetime.now().strftime("%Y-%m-%dT%H:00")
    
    try:
        idx = tuntidata["time"].index(nyt_tunti)
        paine = tuntidata["surface_pressure"][idx]
        print(f"\nTämän hetken ilmanpaine Arjeplogissa: {paine} hPa")
    except ValueError:
        paine = tuntidata["surface_pressure"][0]
        print(f"\nTämän hetken ilmanpaine Arjeplogissa (lähin): {paine} hPa")
        
    # 2. Haetaan tämän päivän aurinkotiedot
    aurinko_nousu = data["daily"]["sunrise"][0].split("T")[1]
    aurinko_lasku = data["daily"]["sunset"][0].split("T")[1]

    print(f"Aurinko nousee tänään: {aurinko_nousu}")
    print(f"Aurinko laskee tänään: {aurinko_lasku}")
    print(f"\nSää- ja ennustedata ladattu onnistuneesti!")

else:
    print(f"Haku epäonnistui. Virhekoodi: {vastaus.status_code}")
    print(f"Palvelimen vastaus: {vastaus.text}")