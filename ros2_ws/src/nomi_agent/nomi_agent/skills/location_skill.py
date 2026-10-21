import requests


class LocationSkill:
    def __init__(self, node=None):
        self.node = node

    def get_user_location(self) -> dict:
        try:
            response = requests.get(
                "https://ipinfo.io/json",
                timeout=5,
            )
            response.raise_for_status()

            data = response.json()

            location = {
                "country": data.get("country", ""),
                "region": data.get("region", ""),
                "city": data.get("city", ""),
            }

            message = (
                "사용자 위치를 확인했습니다. "
                f"{location['country']} "
                f"{location['region']} "
                f"{location['city']}"
            )

            return {
                "success": True,
                "message": message,
                "data": location,
            }

        except Exception as exc:
            message = f"사용자 위치를 확인하지 못했습니다: {exc}"

            if self.node:
                self.node.get_logger().warning(message)

            return {
                "success": False,
                "message": message,
                "data": {},
            }
