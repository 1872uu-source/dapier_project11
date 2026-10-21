import threading

from pathlib import Path
from contextlib import asynccontextmanager

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

ros_node = None
ros_thread = None

ros_ready = threading.Event()
ros_stop = threading.Event()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    message: str


class NomiWebNode(Node):

    def __init__(self):

        super().__init__("nomi_web_server")

        self.command_publisher = self.create_publisher(
            String,
            "/nomi/command",
            10,
        )

        self.latest_response = ""

        self.response_subscriber = self.create_subscription(
            String,
            "/nomi/response",
            self.response_callback,
            10,
        )

        self.get_logger().info(
            "NOMI Web ROS2 Node 시작"
        )
        self.get_logger().info(
            "Publisher: /nomi/command"
        )
        self.get_logger().info(
            "Subscriber: /nomi/response"
        )

    def response_callback(self, message):

        self.latest_response = message.data

        self.get_logger().info(
            f"웹 서버가 받은 NOMI 응답: {self.latest_response}"
        )

    def send_command(self, text):

        message = String()
        message.data = text

        self.command_publisher.publish(message)

        self.get_logger().info(
            f"웹 → ROS2 명령 전송: {text}"
        )


def ros2_worker():

    global ros_node

    try:

        rclpy.init()

        ros_node = NomiWebNode()

        ros_ready.set()

        while rclpy.ok() and not ros_stop.is_set():

            rclpy.spin_once(
                ros_node,
                timeout_sec=0.1,
            )

    except Exception as exc:

        print(
            f"[ROS2] worker 오류: {exc}"
        )

    finally:

        if ros_node is not None:

            try:
                ros_node.destroy_node()
            except Exception:
                pass

            ros_node = None

        if rclpy.ok():
            rclpy.shutdown()


@asynccontextmanager
async def lifespan(app):

    global ros_thread

    ros_ready.clear()
    ros_stop.clear()

    print("========================================")
    print("NOMI Web Server 시작")
    print("ROS2 Worker 시작")
    print("========================================")

    ros_thread = threading.Thread(
        target=ros2_worker,
        daemon=True,
    )

    ros_thread.start()

    if not ros_ready.wait(timeout=10):

        raise RuntimeError(
            "ROS2 Node가 10초 안에 시작되지 않았습니다."
        )

    yield

    print("========================================")
    print("NOMI Web Server 종료")
    print("ROS2 Worker 종료")
    print("========================================")

    ros_stop.set()

    if rclpy.ok():
        rclpy.shutdown()

    if ros_thread is not None:
        ros_thread.join(timeout=3)


app = FastAPI(
    title="NOMI API",
    lifespan=lifespan,
)


@app.get("/api/status")
def status():

    return {
        "success": True,
        "status": "NOMI server running",
        "ros2": (
            ros_node is not None
            and rclpy.ok()
            and ros_ready.is_set()
        ),
    }


@app.post(
    "/api/chat",
    response_model=ChatResponse,
)
def chat(request: ChatRequest):

    if ros_node is None:

        return ChatResponse(
            message="ROS2 Node가 아직 시작되지 않았습니다."
        )

    text = request.message.strip()

    if not text:

        return ChatResponse(
            message="명령을 입력해주세요."
        )

    ros_node.send_command(text)

    return ChatResponse(
        message=f"NOMI 명령 전송: {text}"
    )


@app.get("/api/response")
def response():

    if ros_node is None:

        return {
            "success": False,
            "message": "ROS2 Node가 아직 시작되지 않았습니다.",
        }

    return {
        "success": True,
        "message": ros_node.latest_response,
    }


app.mount(
    "/",
    StaticFiles(
        directory=WEB_DIR,
        html=True,
    ),
    name="web",
)


