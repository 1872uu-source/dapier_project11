# GitHub 저장소 경로 매핑

실행 파일의 import 및 런타임 참조가 깨지지 않도록 소스 패키지 경로는 유지했습니다.

| 인수인계 사본의 위치 | GitHub 저장소 위치 | 처리 |
|---|---|---|
| XLeRobot/ | XLeRobot/ | 경로 유지 |
| ros2_ws/src/nomi_agent | ros2_ws/src/nomi_agent | 경로 유지 |
| ros2_ws/src/nomi_xlerobot_sim | ros2_ws/src/nomi_xlerobot_sim | 경로 유지 |
| ros2_ws/src/nomi_rviz_bridge | ros2_ws/src/nomi_rviz_bridge | 경로 유지 |
| 루트 SETUP_AND_RUN.md 등 5개 가이드 | docs/ | 문서만 이동 |
| 루트 README.md | README.md | 협업용으로 다시 작성 |
| 인수인계 manifests/ | 저장소에서 제외 | 전달 패키지 SHA 및 경로 목록은 Git 실행 자산이 아니며 이 재배치로 오래된 경로가 됨 |

MuJoCo Host, Agent 목적지 로더, RViz launch와 Mock 스크립트는 홈 아래 XLeRobot 및 ros2_ws 경로를 참조합니다. 새 Clone은 두 경로에 심볼릭 링크를 만들어 호환시킵니다. 동작 코드는 바꾸지 않았습니다.
