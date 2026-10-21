import requests


class WeatherSkill:
    def __init__(self, node=None):
        self.node = node

    def _geocode(self, city: str) -> dict | None:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": city,
                "count": 1,
                "language": "ko",
                "format": "json",
            },
            timeout=10,
        )
        response.raise_for_status()

        results = response.json().get("results", [])

        if not results:
            return None

        return results[0]

    def get_weather(self, city: str = "서울") -> dict:
        try:
            place = self._geocode(city)

            if not place:
                return {
                    "success": False,
                    "message": f"'{city}'의 위치를 찾지 못했습니다.",
                }

            latitude = place["latitude"]
            longitude = place["longitude"]
            place_name = place.get("name", city)

            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,"
                        "relative_humidity_2m,"
                        "apparent_temperature,"
                        "weather_code,"
                        "wind_speed_10m"
                    ),
                    "timezone": "auto",
                },
                timeout=10,
            )
            response.raise_for_status()

            current = response.json().get("current", {})

            temperature = current.get("temperature_2m")
            apparent_temperature = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            wind_speed = current.get("wind_speed_10m")

            message = (
                f"{place_name} 현재 날씨입니다. "
                f"기온 {temperature}도, "
                f"체감온도 {apparent_temperature}도, "
                f"습도 {humidity}%, "
                f"풍속 {wind_speed}km/h입니다."
            )

            return {
                "success": True,
                "message": message,
                "data": {
                    "city": place_name,
                    "temperature": temperature,
                    "apparent_temperature": apparent_temperature,
                    "humidity": humidity,
                    "wind_speed": wind_speed,
                    "weather_code": current.get("weather_code"),
                },
            }

        except Exception as exc:
            message = f"날씨 정보를 가져오지 못했습니다: {exc}"

            if self.node:
                self.node.get_logger().warning(message)

            return {
                "success": False,
                "message": message,
                "data": {},
            }
