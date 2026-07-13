from fmiopendata.wfs import download_stored_query
from datetime import datetime, timedelta
import zoneinfo

# Inarin koordinaatit
lat, lon = 68.9050, 27.0080
paikka_str = f"latlon={lat:.4f},{lon:.4f}"

# Määritetään aloitusaika ja haetaan dataa 66 tuntia eteenpäin (koko ennusteen pituus)
start_t = datetime.now(zoneinfo.ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:00:00Z")
end_t = (datetime.now(zoneinfo.ZoneInfo("UTC")) + timedelta(hours=66)).strftime("%Y-%m-%dT%H:00:00Z")

print("Haetaan FMI:n raakaa sadedataa (66h jakso)...")
fmi_data = download_stored_query(
    "fmi::forecast::harmonie::surface::point::multipointcoverage",
    args=[paikka_str, f"starttime={start_t}", f"endtime={end_t}", "timeseries=True"]
)

if fmi_data and fmi_data.data:
    eka_asema = list(fmi_data.data.keys())[0]
    asema_data = fmi_data.data[eka_asema]
    
    ajat = asema_data.get("times", [])
    sateet = asema_data.get("Precipitation amount", {}).get("values", [])
    
    print("\nAika (UTC)          | Sademäärän raaka-arvo FMI:ltä")
    print("-" * 55)
    # Poistettu [:20] rajoitus, jotta näemme koko listan keskiviikolle asti
    for t, s in zip(ajat, sateet):
        print(f"{t} | {s}")
else:
    print("Datan haku epäonnistui.")