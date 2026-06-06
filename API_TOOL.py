import os
import requests
from dotenv import load_dotenv
from typing import Annotated
from langchain_core.tools import InjectedToolArg, tool

# Load keys from the .env file
load_dotenv()

class APIAGENT:
    def __init__(self):
        self.weather_key = os.getenv("WEATHER_KEY")
        self.currency_key = os.getenv("CURRENCY_CONVERSION_KEY")
        self.news_key = os.getenv("NEWS_KEY")
        self.nasa_key = os.getenv("NASA_KEY")

    def get_tool(self):
        """Generates and returns isolated, fully bound tools for LangChain & LangGraph Agents."""
        
        @tool
        def get_conversion_factor(base_currency: str, target_currency: str) -> dict:
            """Get the conversion factor between two currencies."""
            url = f'https://exchangerate-api.com{self.currency_key}/pair/{base_currency}/{target_currency}'
            response = requests.get(url)
            return response.json()

        @tool
        def convert(base_currency_value: str, conversion_rate: Annotated[float, InjectedToolArg]) -> float:
            """Given a currency conversion rate and base currency value, this function calculates the target currency value."""
            return float(base_currency_value) * conversion_rate
        
        @tool 
        def weather_detector(city: str) -> str:
            """Fetch the current weather and temperature for a given city name. 
            Use this whenever a user asks about the weather, climate, or temperature.
            """
            url = "https://openweathermap.org"
            params = {
                "q": city,
                "appid": self.weather_key,
                "units": "metric",
            }
            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                condition = data['weather'][0]['description']
                temperature = data['main']['temp']
                return f"The weather in {city.title()} is '{condition}' at {temperature}°C."
            except requests.RequestException:
                return f"Sorry, I couldn't fetch the weather data for {city}. Please try again later."

        @tool
        def locate_me() -> dict:
            """Finds the terminal user's current latitude and longitude using geolocation."""
            try:
                # Use standard JSON endpoint format for ip-api
                response = requests.get("http://ip-api.com").json()
                return {"lat": response.get("lat"), "lon": response.get("lon"), "city": response.get("city")}
            except Exception as e:
                return {"error": f"Failed to retrieve location data: {str(e)}"}

        @tool
        def get_temperature(lat: float, lon: float) -> str:
            """Gets the current temperature using exact latitude and longitude coordinates."""
            url = "https://open-meteo.com"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true"
            }
            try:
                response = requests.get(url, params=params).json()
                temp = response["current_weather"]["temperature"]
                return f"{temp}°C"
            except Exception:
                return "Could not retrieve temperature from coordinate path."
        
        @tool
        def analyze_domain_host(domain: str) -> dict:
            """Finds the network hosting provider, country, and ISP of any website domain name.
            Args:
                domain: The website URL or name (e.g., 'github.com', 'openai.com').
            """
            url = f"https://ipinfo.io{domain}/json"
            response = requests.get(url)
            if response.status_code != 200:
                return {"error": "Could not resolve domain network path."}
            
            data = response.json()
            return {
                "hosting_company": data.get('org'),
                "country": data.get('country'),
                "city": data.get('city')
            }

        @tool
        def define_technical_word(word: str) -> str:
            """Looks up the official dictionary definition and synonyms for a specific word.
            Args:
                word: A single English word to define.
            """
            url = f"https://dictionaryapi.dev{word}"
            response = requests.get(url)
            
            if response.status_code != 200:
                return f"Could not find a definition for '{word}'."
                
            data = response.json()
            try:
                # Fixed dictionary extraction schema pathing
                definition = data[0]["meanings"][0]["definitions"][0]["definition"]
                return definition
            except (IndexError, KeyError, TypeError):
                return "Definition structure parsing failed."

        @tool
        def nasa_result(query: str) -> dict:
            """Searches NASA's image and video library for media related to a specific query term.
            Args:
                query: A search term related to space, astronomy, or NASA missions.
            """
            url = f"https://nasa.gov{query}"  
            response = requests.get(url)
            if response.status_code == 200:
                items = response.json().get('collection', {}).get('items', [])
                simplified_result = []
                for item in items[:3]:
                    try:
                        simplified_result.append({
                            "title": item['data'][0]['title'],
                            "description": item['data'][0]['description'],
                            "media_type": item['data'][0]['media_type'],
                            "url": item['links'][0]['href']
                        })  
                    except (KeyError, IndexError):
                        continue
                return simplified_result
            return {"error": "NASA API request failed."}

        @tool
        def nasa_mars_weather() -> dict:
            """Fetches the latest weather data from NASA's InSight Mars lander."""
            url = f"https://nasa.gov{self.nasa_key}&feedtype=json&ver=1.0"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                sol_keys = data.get("sol_keys", [])
                if sol_keys:
                    latest_sol = sol_keys[-1]
                    weather_info = data[latest_sol]
                    return {
                        "sol": latest_sol,
                        "temperature": weather_info.get("AT", {}).get("av"),
                        "wind_speed": weather_info.get("HWS", {}).get("av"),
                        "pressure": weather_info.get("PRE", {}).get("av")
                    }
                return {"error": "No sol data available."}
            return {"error": "NASA Mars weather API request failed."}

        return [
            get_conversion_factor,
            convert,
            weather_detector,
            locate_me,
            get_temperature,
            analyze_domain_host,
            get_conversion_factor,
            define_technical_word,
            nasa_result,
            nasa_mars_weather
        ]
