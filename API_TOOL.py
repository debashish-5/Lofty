import os
from langchain_protocol import Annotated
import requests
from dotenv import load_dotenv
from langchain_core.tools import InjectedToolArg, tool, BaseTool
from langchain_core.messages import HumanMessage
import requests
from typing import Annotated
import json
# Load keys from the .env file
load_dotenv()

class APIAGENT:
    def __init__(self):
        self.weather_key = os.getenv("WEATHER_KEY")
        self.currency_key = os.getenv("CURRENCY_CONVERSION_KEY")
        self.news_key = os.getenv("NEWS_KEY")
        self.nasa_key = os.getenv("NASA_KEY")
    @tool
    def get_conversion_factor(self,base_currency:str,target_currency:str) -> float:
        """Get the conversion factor between two currencies."""
        url = f'https://v6.exchangerate-api.com/v6/{self.currency_key}/pair/{base_currency}/{target_currency}'
        response = requests.get(url)
        data = response.json()
        return response.json()
    @tool
    def convert(self,base_currency_value:str,conversion_rate: Annotated[float,InjectedToolArg]) -> float:
        """Given a currency conversion rate and base currency value,this function calculates the target currency value"""
        return float(base_currency_value) * conversion_rate
    
    @tool 
    def weather_detector(self,city:str) -> str:
        """Fetch the current weather and temperature for a given city name. 
            Use this whenever a user asks about the weather, climate, or temperature.
        """
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q":city,
            "appid":self.weather_key,
            "units":"metric",
        }
        try:
            response = requests.get(url,params=params)
            response.raise_for_status()
            data = response.json()
            condition = data['weather'][0]['description']
            temperature = data['main']['temp']
            return f"The weather in {city.title()} is '{condition}' at {temperature}°C."
        except requests.RequestException as e:
            return f"Sorry, I couldn't fetch the weather data for {city}. Please try again later."
    @tool
    def locate_me() -> dict:
        """Finds the terminal user's current latitude and longitude."""
        # No API key needed!
        response = requests.get("http://ip-api.com").json()
        return {"lat": response["lat"], "lon": response["lon"], "city": response["city"]}

    @tool
    def get_temperature(lat: float, lon: float) -> str:
        """Gets the current temperature using exact latitude and longitude coordinates."""
        # No API key needed!
        url = f"https://open-meteo.com{lat}&longitude={lon}&current_weather=true"
        response = requests.get(url).json()
        temp = response["current_weather"]["temperature"]
        return f"{temp}°C"
    
    @tool
    def analyze_domain_host(domain:str) -> dict:
        """Finds the network hosting provider, country, and ISP of any website domain name.
        Args:
            domain: The website URL or name (e.g., 'github.com', 'openai.com').
        """
        url = f"https://ipinfo.io/{domain}"
        response = requests.get(url)
        if response.get("status") == "failed":
            return {"error":"Could not resolve domain network path."}
        return {
            "hosting_company":response.get('isp'),
            "country":response.get('country'),
            "city":response.get('city')
        }
    @tool
    def define_technical_word(word: str) -> str:
        """Looks up the official dictionary definition and synonyms for a specific word.
        Args:
            word: A single English word to define.
        """
        # No API key required!
        url = f"https://dictionaryapi.dev{word}"
        response = requests.get(url)
        
        if response.status_code != 200:
            return f"Could not find a definition for '{word}'."
            
        data = response.json()
        try:
            # Pull the primary definition from the payload
            definition = data[0]["meanings"][0]["definitions"][0]["definition"]
            return definition
        except (IndexError, KeyError):
            return "Definition structure parsing failed."
        

    @tool
    def nasa_result(query:str) -> dict:
        """Searches NASA's image and video library for media related to a specific query term.
        Args:
            query: A search term related to space, astronomy, or NASA missions (e.g., 'Mars rover', 'Hubble telescope').
        """
        url = f"https://images-api.nasa.gov/search?q={query}"  
        response = requests.get(url)
        if response.status_code == 200:
            items = response.json().get('collection',{}).get('items',[])
            #clean and parse top 3 result 
            simplified_result = []
            for item in items[:3]:
                try:
                    title = item['data'][0]['title']
                    description = item['data'][0]['description']
                    media_type = item['data'][0]['media_type']
                    url_link = item['links'][0]['href']
                    simplified_result.append({
                        "title": title,
                        "description": description,
                        "media_type": media_type,
                        "url": url_link
                    })  
                except (KeyError, IndexError):
                    continue
            return simplified_result
        else:
            return {"error": "NASA API request failed."}
    @tool
    def nasa_mars_weather() -> dict:
        """Fetches the latest weather data from NASA's InSight Mars lander."""
        url = f"https://api.nasa.gov/insight_weather/?api_key={self.nasa_key}&feedtype=json&ver=1.0"
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
            else:
                return {"error": "No sol data available."}
        else:
            return {"error": "NASA Mars weather API request failed."}
    def get_tool(self):
        """Return a tools for Langchain &  langGraph Agents."""
        return [
            self.get_conversion_factor,
            self.convert,
            self.weather_detector,
            self.locate_me,
            self.get_temperature,
            self.analyze_domain_host,
            self.define_technical_word,
            self.nasa_result,
            self.nasa_mars_weather
        ]
    
