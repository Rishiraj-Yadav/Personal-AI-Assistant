#!/usr/bin/env python3
"""
Weather Checker Skill
Gets current weather using wttr.in API
"""
import os
import json
import sys
import urllib.request
import urllib.parse


def get_weather(city: str, format_type: str = "simple"):
    """
    Get weather for a city
    
    Args:
        city: City name
        format_type: 'simple' or 'detailed'
        
    Returns:
        Dict with weather information
    """
    # Use wttr.in API with JSON format
    city_encoded = urllib.parse.quote(city)
    url = f"https://wttr.in/{city_encoded}?format=j1"
    
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
        
        # Extract current conditions
        current = data["current_condition"][0]
        location = data["nearest_area"][0]
        
        result = {
            "city": city,
            "location": {
                "name": location.get("areaName", [{}])[0].get("value", city),
                "country": location.get("country", [{}])[0].get("value", ""),
                "region": location.get("region", [{}])[0].get("value", "")
            },
            "current": {
                "temperature_c": current.get("temp_C"),
                "temperature_f": current.get("temp_F"),
                "feels_like_c": current.get("FeelsLikeC"),
                "feels_like_f": current.get("FeelsLikeF"),
                "condition": current.get("weatherDesc", [{}])[0].get("value"),
                "humidity": current.get("humidity"),
                "wind_speed_kmph": current.get("windspeedKmph"),
                "wind_speed_mph": current.get("windspeedMiles"),
                "wind_direction": current.get("winddir16Point"),
                "precipitation_mm": current.get("precipMM"),
                "visibility_km": current.get("visibility"),
                "uv_index": current.get("uvIndex")
            }
        }
        
        if format_type == "detailed":
            # Add forecast
            result["forecast"] = []
            for day in data.get("weather", [])[:3]:  # Next 3 days
                result["forecast"].append({
                    "date": day.get("date"),
                    "max_temp_c": day.get("maxtempC"),
                    "max_temp_f": day.get("maxtempF"),
                    "min_temp_c": day.get("mintempC"),
                    "min_temp_f": day.get("mintempF"),
                    "condition": day.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value")
                })
        
        # Create human-readable summary
        temp = current.get("temp_C")
        condition = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
        feels = current.get("FeelsLikeC")
        
        result["summary"] = (
            f"Current weather in {result['location']['name']}: "
            f"{condition}, {temp}°C (feels like {feels}°C). "
            f"Humidity: {current.get('humidity')}%, "
            f"Wind: {current.get('windspeedKmph')} km/h {current.get('winddir16Point')}"
        )
        
        return result
        
    except urllib.error.URLError as e:
        raise Exception(f"Failed to fetch weather data: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Failed to parse weather data: {str(e)}")


def main():
    """Main entry point"""
    try:
        # Get parameters from environment
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        city = params.get("city")
        if not city:
            print(json.dumps({
                "error": "Missing required parameter: city"
            }))
            sys.exit(1)
        
        format_type = params.get("format", "simple")
        
        # Get weather
        result = get_weather(city, format_type)
        
        # Output result as JSON
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(json.dumps({
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()