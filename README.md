# NOMI — XLeRobot 통합 개발 저장소

ROS 2 Jazzy 기반 NOMI Agent, 웹 제어 앱, MuJoCo 시뮬레이션 및 로봇암 통합 인터페이스를 함께 관리하는 협업 저장소입니다.

## 현재 범위

- 자연어 명령을 Tool Registry와 Execution Harness로 검증해 ROS 기능에 전달
- Ollama Qwen3.5 9B 프로필 및 기존 Qwen + Hermes 프로필
- React/TypeScript 웹 UI, FastAPI/Socket.IO, ZeroMQ 브리지
- MuJoCo Host, 실내 테스트 장면, RViz 상태 브리지
- 팀원 개발 로봇암 모듈과 연동할 Tool/Skill 경계

LLM은 경로 계획, 물체 인식 또는 직접 관절·바퀴 제어를 수행하지 않습니다. 각 기능 모듈이 실행과 상태 검증을 맡습니다.

## 저장소 구조

- XLeRobot/web_control: 프런트엔드, 백엔드, 공유 목적지 파일 및 Mock 개발 실행 스크립트
- XLeRobot/simulation/mujoco: MuJoCo XML, STL 메시, 주행 보조 코드와 테스트
- XLeRobot/simulation/xlerobot_urdf: RViz용 URDF 및 에셋
- ros2_ws/src/nomi_agent: LLM, Tool Registry, SafetyGuard, Harness, Skills, 테스트
- ros2_ws/src/nomi_xlerobot_sim: MuJoCo ROS Host 및 launch 설정
- ros2_ws/src/nomi_rviz_bridge: Odometry, Path, Marker 브리지
- docs: 설치, ROS 및 로봇암 통합, 테스트, 알려진 문제
- scripts 및 tests: 저장소 레벨 안내. 실제 실행 스크립트와 테스트는 경로 의존성을 위해 각 패키지에 유지

## 검증 상태

사용자가 제공한 이전 시험 기록에 따르면 웹 UI의 비이동 LLM 통합 A–E와 별도 MuJoCo 테이블 1·3 주행은 통과했습니다. 이 저장소 준비 작업에서는 MuJoCo 주행과 LLM 추론을 하지 않았습니다. LLM 자연어 명령에 의한 실제 목적지 주행, 실물 로봇 동작, 로봇암 통합은 미검증입니다. 자세한 범위는 docs/TEST_RESULTS.md 및 docs/KNOWN_ISSUES.md를 읽으세요.

## 설치

새 Ubuntu 24.04 컴퓨터에서 Clone, ROS, Python, Ollama, 프런트엔드 설정을 진행하는 순서는 docs/SETUP_AND_RUN.md에 있습니다. 현재 코드가 기존 홈 경로 XLeRobot 및 ros2_ws를 참조하므로 문서에 안내된 심볼릭 링크를 설정합니다.

## 브랜치 및 협업 정책

- main: 검증된 통합 코드만 병합
- feature/llm-web: LLM, 웹앱 및 NOMI Tool/Harness 변경
- feature/robot-arm: 로봇암 학습·추론·제어 모듈

작업 브랜치에서 변경하고 Pull Request로 제안하세요. 병합 전에는 ROS 토픽과 메시지 타입 충돌, package.xml 의존성, 안전 가드, 테스트 및 양쪽 모듈 통합 동작을 함께 검토합니다. 직접 main에 커밋하지 않습니다.

## 라이선스 및 자산

저장소 최상위 LICENSE 및 XLeRobot/LICENSE를 확인하세요. 포함된 외부 코드/메시/모델 자산의 원래 라이선스 고지를 보존하고, 재배포 권한이 확인되지 않은 새 파일은 추가하지 마세요.
