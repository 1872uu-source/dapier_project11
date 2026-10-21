# 알려진 문제

1. 실제 자연어 명령을 이용한 자동 주행은 최종 종단 검증되지 않았습니다. LLM UI 비이동 테스트와 별도 MuJoCo 테이블 1/3 주행 성공을 혼동하지 마세요.
2. pick_object/place_object는 현재 실패를 반환하는 미구현 Skill입니다.
3. open_gripper/close_gripper 성공은 ROS 메시지 발행 성공이며 물리적 완료/그립 증거가 아닙니다.
4. arm_command를 연결하는 NOMI Tool이 없습니다.
5. 웹 UI 활성 모델 라벨이 Agent의 model_status 확인 전에는 실제 선택 모델과 다르게 보일 수 있습니다.
6. 동일 ROS_DOMAIN_ID에 Agent를 중복 실행하면 요청/응답 경쟁 가능성이 있습니다. 먼저 ros2 node list로 확인하세요.
7. Ollama 첫 모델 로드나 긴 요청에서 timeout/EOF가 과거 관측되었습니다. 이미 수행한 비멱등 Tool을 자동 재요청하지 마세요.
8. 과거 ROS 종료 시 이미 종료된 context에 shutdown을 다시 호출하는 로그가 관측되었습니다.
9. Ollama 모델 바이너리, ROS 설치, Python 가상환경, Node/pnpm, node_modules는 패키지 외부 의존성입니다.

실물 로봇 적용 전에는 암 모듈의 관절 제한, 실행 acknowledgement, 취소, timeout, watchdog, 실제 상태 피드백을 별도로 검증해야 합니다.
