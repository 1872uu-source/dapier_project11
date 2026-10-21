# ROS 인터페이스

아래는 전달 소스에서 확인한 인터페이스입니다. 사용자 정의 ROS 메시지 대신 std_msgs/msg/String 안에 JSON을 사용하는 토픽이 많습니다.

## NOMI 웹 브리지와 Agent
| 토픽 | 타입 | 방향 | 용도 |
|---|---|---|---|
| /nomi/command | std_msgs/msg/String | 웹 브리지 → Agent | request_id 및 자연어 명령 JSON |
| /nomi/response | std_msgs/msg/String | Agent → 웹 브리지 | 응답 및 요청 ID |
| /nomi/task_status | std_msgs/msg/String | Agent → 웹 브리지 | Harness 단계/상태 |
| /nomi/cancel | std_msgs/msg/String | 웹 브리지 → Agent | 취소 요청 |
| /nomi/model_switch | std_msgs/msg/String | 웹 브리지 → Agent | 프로필 변경 |
| /nomi/model_status | std_msgs/msg/String | Agent → 웹 브리지 | 프로필 결과 |
| /nomi/navigation_destinations | std_msgs/msg/String | 웹 브리지 → Agent | 목적지 목록 JSON |
| /nomi/navigation_request | std_msgs/msg/String | Navigation Skill → 웹 브리지 | 목적지 주행 요청 |
| /nomi/navigation_cancel | std_msgs/msg/String | Skill → 웹 브리지 | 주행 취소 |
| /nomi/navigation_result | std_msgs/msg/String | 웹 브리지 → Agent | 이동 결과/완료 정보 |

## MuJoCo Host
| 토픽 | 타입 | 방향 | 용도 |
|---|---|---|---|
| /nomi/xlerobot/state | std_msgs/msg/String | Host → Agent/브리지 | 위치, yaw, 속도, 센서 JSON |
| /nomi/xlerobot/base_cmd_vel | geometry_msgs/msg/Twist | Navigation Skill → Host | base velocity 명령 |
| /nomi/xlerobot/arm_command | std_msgs/msg/String | Host 구독, NOMI Tool 발행 없음 | JSON arm, joint_index, angle |
| /nomi/xlerobot/gripper_command | std_msgs/msg/String | Gripper Skill → Host | 현재 JSON arm, angle |
| /nomi/xlerobot/reset | std_msgs/msg/String | Host 구독 | 시뮬레이터 reset |

웹앱 자동 주행은 별도 Socket.IO → Python RemoteCore → ZMQ 경로를 거쳐 MuJoCo Host로 전달됩니다. Host ZMQ 기본 주소는 명령 127.0.0.1:5555, 상태 127.0.0.1:5556입니다.

## RViz
| 토픽 | 타입 | 발행자 | 내용 |
|---|---|---|---|
| /nomi/rviz/odom | nav_msgs/msg/Odometry | nomi_rviz_bridge | odometry 표시 |
| /nomi/rviz/trajectory | nav_msgs/msg/Path | nomi_rviz_bridge | 궤적 |
| /nomi/rviz/robot_marker | visualization_msgs/msg/Marker | nomi_rviz_bridge | 로봇 marker |

원천 상태는 /nomi/xlerobot/state입니다. xlerobot_state.launch.py는 robot_state_publisher, RViz bridge와 선택적 RViz를 띄우며 ~/XLeRobot/simulation/xlerobot_urdf/xlerobot/xlerobot.urdf를 요구합니다.

## 목적지
공유 기준 데이터는 XLeRobot/web_control/shared/navigation_destinations.json입니다. 프레임은 xlerobot_map이며 Agent는 웹 브리지에서 검증되어 동기화된 저장 좌표를 조회합니다. MuJoCo static map과 실제 SLAM/Nav2 map을 동일시하면 안 됩니다.
