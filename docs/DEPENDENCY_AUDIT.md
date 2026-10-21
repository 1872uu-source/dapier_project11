# 의존성 및 환경 감사

## 확인한 파일·구조
- ROS package.xml 및 ament_python setup.py: nomi_agent, nomi_xlerobot_sim, nomi_rviz_bridge
- MuJoCo Host가 여는 scene.xml과 compiler meshdir 및 참조 STL 에셋
- RViz launch가 읽는 URDF와 mesh
- 웹 클라이언트 package.json, package-lock.json, pnpm-lock.yaml, Vite 설정
- 웹 서버 requirements.txt
- MuJoCo simulation/mujoco/requirements.txt
- Agent setup.py 의존성 및 .env.example

## 새 컴퓨터에서 제공해야 하는 외부 환경
- Ubuntu 24.04 및 ROS 2 Jazzy 설치
- Python 3.12와 ROS의 rclpy/메시지 패키지
- ROS 외 Python 의존성을 설치할 system-site-packages 가상환경
- MuJoCo Python 바인딩과 MuJoCo 패키지 requirements
- Ollama 서비스와 별도 내려받은 qwen3.5:9b 모델
- Node.js 22.12 이상(또는 Vite 요구에 맞는 20.19 이상), pnpm
- 인터넷 또는 미리 준비된 apt/pip/pnpm 패키지 저장소

## 현재의 경로 제약
MuJoCo Host는 Path.home()/XLeRobot/simulation/mujoco/scene.xml, 목적지 로더의 기본 경로는 ~/XLeRobot/web_control/shared/navigation_destinations.json, RViz launch는 ~/XLeRobot/simulation/xlerobot_urdf/...를 사용합니다. Mock Agent 개발 스크립트는 ~/XLeRobot과 ~/ros2_ws를 사용합니다. 설치 가이드는 Clone 사본에서 두 홈 경로를 가리키는 심볼릭 링크를 설정합니다.

NOMI_NAVIGATION_DESTINATIONS_FILE을 쓰면 목적지 경로를 명시할 수 있지만 MuJoCo Host와 launch 경로는 홈 경로 기준이므로 심볼릭 링크가 필요합니다. 사용자 계정명이 포함된 절대 경로는 코드에서 발견하지 못했습니다.

## 의존성 잠금 한계
웹 클라이언트에는 npm과 pnpm lockfile이 모두 포함됩니다. Python 서버 requirements와 simulation requirements에는 넓거나 핀되지 않은 일부 항목이 있습니다. 따라서 다른 컴퓨터에서 새로 설치한 결과가 운영 가상환경과 바이트 단위로 동일하다고 보장하지 않습니다. pip/rosdep 설치는 이 사본 작업에서 실행하지 않았습니다.
