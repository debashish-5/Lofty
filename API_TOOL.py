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
        

            