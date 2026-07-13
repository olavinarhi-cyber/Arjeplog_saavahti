import requests
from datetime import datetime, timedelta
import zoneinfo
from fmiopendata.wfs import download_stored_query

def testaa_fmi():
    print("--- TESTATAAN FMI (Juutuanjoki) ---")
    lat, lon = 68.9050, 27.0080
    paikka_str = f"latlon={lat:.4f},{lon:.4f}"
    start_t = datetime.now(zoneinfo.ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:00:00Z")
    end_t = (datetime.now(zoneinfo.ZoneInfo("UTC")) + timedelta(days=2)).strftime("%Y-%m-%dT%H:00:00Z")
    
    try:
        fmi_data = download_stored_query("fmi::forecast::harmonie::surface::point::multipointcoverage",
                                         args=[paikka_str, f"starttime={start_t}", f"endtime={end_t}"])
        if fmi_data and fmi_data.data:
            latest_loc = list(fmi_data.data.keys())[0]
            ts_dict = fmi_data.data[latest_loc]["timeseries"]
            print(f"✅ FMI haku onnistui! Löytyi {len(ts_dict)} aikapistettä.")
            # Tulostetaan ensimmäisen tunnin parametrit nähtäville
            eka_aika = list(ts_dict.keys())[0]
            print(f"Esimerkkidataa ({eka_aika}):", ts_dict[eka_aika].keys())
        else:
            print("❌ FMI palautti tyhjää dataa.")
    except Exception as e:
        print(f"❌ FMI kaatui virheeseen: {e}")

def testaa_smhi():
    print("\n--- TESTATAAN SMHI (Miekak) ---")
    lat, lon = 66.7630, 17.2340
    # SMHI vaatii koordinaatit usein pyöristettynä 4 desimaaliin
    url_smhi = f"https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon:.4f}/lat/{lat:.4f}/data.json"
    
    try:
        res = requests.get(url_smhi, timeout=10)
        print(f"SMHI Status code: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            series = data.get("timeSeries", [])
            print(f"✅ SMHI haku onnistui! Löytyi {len(series)} aikapistettä.")
            if series:
                print("Esimerkkidataa (SMHI):", series[0].get("data", {}).keys())
        else:
            print(f"❌ SMHI rajapinta palautti virhekoodin: {res.text[:200]}")
    except Exception as e:
        print(f"❌ SMHI kaatui virheeseen: {e}")

if __name__ == "__main__":
    testaa_fmi()
    testaa_smhi()