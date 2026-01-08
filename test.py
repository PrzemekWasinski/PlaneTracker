import requests

icao = "347488"

def fetch_plane_info(icao):
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{icao}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            api_data = response.json()
            
            manufacturer = clean_string(str(api_data.get("Manufacturer", "-")))
            if manufacturer == "Avions de Transport Regional":
                manufacturer = "ATR"
            elif manufacturer == "Honda Aircraft Company":
                manufacturer = "Honda"
            
            return {
                "manufacturer": manufacturer,
                "registration": clean_string(str(api_data.get("Registration", "-"))),
                "owner": clean_string(str(api_data.get("RegisteredOwners", "-"))),
                "model": clean_string(str(api_data.get("Type", "-")))
            }
        else: #Backup API
            url = f"https://opensky-network.org/api/metadata/aircraft/icao/{icao}"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                api_data = response.json()

                output = {
                    "manufacturer": api_data.get("model", "-").split(" ", 1)[0],
                    "registration": api_data.get("registration", "-"),
                    "owner": api_data.get("operator", "-"),
                    "model": api_data.get("model", "-").split(" ", 1)[1]
                }

                if output.get("manufacturer") == '' or output.get("registration") == '' or output.get("owner") == '' or output.get("model") == '':
                    return None

                return output

    except Exception as e:
        print(f"API error for {icao}: {e}")
    
    return None

print(fetch_plane_info("800584"))