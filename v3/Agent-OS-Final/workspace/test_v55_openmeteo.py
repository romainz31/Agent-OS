import requests

def get_weather_data(latitude, longitude, current_weather=False, hourly=None, daily=None, timezone=None, start_date=None, end_date=None, timezone_offset=None, timezone_name=None, extra_parameters=None):
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude
    }
    
    if current_weather:
        params["current_weather"] = "true"
    
    if hourly:
        params["hourly"] = hourly
    
    if daily:
        params["daily"] = daily
    
    if timezone:
        params["timezone"] = timezone
    
    if start_date:
        params["start_date"] = start_date
    
    if end_date:
        params["end_date"] = end_date
    
    if timezone_offset:
        params["timezone_offset"] = timezone_offset
    
    if timezone_name:
        params["timezone_name"] = timezone_name
    
    if extra_parameters:
        params["extra_parameters"] = extra_parameters
    
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        return None

# Exemple d'utilisation
if __name__ == "__main__":
    data = get_weather_data(latitude=48.8566, longitude=2.3522, current_weather=True, hourly="temperature_2m,relativehumidity_2m,precipitation")
    print(data)