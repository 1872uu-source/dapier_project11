# 로봇암 협업 및 NOMI 통합 계약

## 실행 흐름

사용자 자연어 → LLM의 도구 선택/인자 → Tool Registry 스키마와 SafetyGuard 검증 → ExecutionHarness 순서·상태 관리 → Manipulation Skill → ROS 암 실행 모듈 → 상태/evidence → Harness 결과 → 웹 UI 응답.

LLM은 관절 위치, 토크, raw actuator 값을 직접 발행하지 않습니다. 검증된 작업 이름·대상·장소를 Skill API로 전달합니다.

## 현재 코드 상태

| Tool/토픽 | 입력 | 현재 동작과 완료 기준 |
|---|---|---|
| open_gripper | Tool 인자 없음; std_msgs/msg/String, /nomi/xlerobot/gripper_command의 {arm:left, angle:0.7} JSON | publish 직후 success 반환; 관절 도달 확인 없음 |
| close_gripper | Tool 인자 없음; 같은 토픽에 {arm:left, angle:-0.7} JSON | publish 직후 success 반환; 그립 확인 없음 |
| pick_object | object_name 문자열 | Registry 등록; Skill은 인식/접근이 연결되지 않았다며 실패 반환 |
| place_object | location 문자열 | Registry 등록; Skill은 인식/접근이 연결되지 않았다며 실패 반환 |
| arm_command | std_msgs/msg/String, /nomi/xlerobot/arm_command, JSON의 arm, joint_index, angle | MuJoCo Host 구독만 존재; NOMI Tool이 발행하지 않음 |
| gripper_command | std_msgs/msg/String, /nomi/xlerobot/gripper_command, JSON의 arm, angle | open/close Skill이 발행; 결과 acknowledgement 없음 |

현재 success는 gripper 토픽 publish가 이뤄졌다는 뜻이며 물리적 완료가 아닙니다. MuJoCo Host의 arm callback은 목표 actuator를 설정하고 오류를 로그로 남기지만 요청 결과 토픽을 제공하지 않습니다.

## 팀원이 제공할 권장 ROS API

장기 동작에는 feedback, cancel, result를 제공하는 ROS 2 Action을 권장합니다.

### Goal
- request_id 또는 task_id (중복 방지)
- operation: pick/place/open/close 또는 허용된 작업
- 검증된 object_id와 perception pose/frame_id 또는 허용된 named location
- timeout 및 명시된 작업 제약

### Feedback
- 현재 단계, 진행률, 관절 상태 또는 안전한 목표 상태
- monotonic step ID와 처리 중인 request_id

### Result
- success, status, error_code, message, request_id
- completed_steps, duration_ms
- evidence: 관절 도달, 그리퍼/접촉/물체 보유 확인
- 실패·취소 시 마지막으로 확인된 안전 상태

기존 웹앱 /nomi/command의 request_id와 작업 ID correlation을 보존합니다. 같은 request_id 재전송은 동작을 중복 실행하지 말고 기존 task 결과/상태를 반환해야 합니다.

## 안전, timeout 및 취소

- joint 이름, rad 단위, 제한, 속도/가속도, 작업 공간 및 frame을 API 문서에 명시합니다.
- task cancel을 Action cancel로 연결합니다. emergency stop은 별도의 하드웨어 독립 안전 인터페이스로 둡니다.
- LLM timeout 뒤 실행 완료 여부가 불명확하면 비멱등 작업을 자동 재실행하지 않습니다.
- timeout, cancel, 통신 단절, partial motion, controller error를 구분합니다.
- 다음 단계는 이전 결과가 실제 상태 evidence로 성공 확인됐을 때만 진행합니다.
- LLM이 임의 관절값을 보내는 일반적인 set-joint Tool을 노출하지 않습니다.

## NOMI 연결 지점

- ToolRegistry._build_specs(): schema, 필수 인자, timeout, mutation category 및 completion evidence
- SafetyGuard: 대상·목적지 모호성, 부정 명령, pick/place 순서
- ManipulationSkill: 팀 Action client adapter
- ExecutionHarness: task 상태, 순서, 취소, 실패 후 중단 및 실제 evidence 기반 성공
- agent_node.py: Action lifecycle, request ID correlation 및 task_status/response 발행
- tests: MockArm으로 정상/실패/timeout/cancel/중복 및 순차 실행 검증
- web bridge/UI: task ID와 단계별 상태 표시

## 통합 순서

1. 팀원이 ROS package, Action 정의, 이름, joint/unit/frame 계약을 PR에서 제안합니다.
2. 별도 feature/robot-arm 브랜치에 Action server와 MockArm을 추가합니다.
3. 잘못된 대상, joint limit, 대상 미검출, timeout, cancel, 중복 요청, partial failure 테스트를 통과합니다.
4. NOMI adapter와 Harness를 연결하고 evidence 없이는 success가 되지 않는지 검증합니다.
5. MuJoCo/Mock 테스트 뒤 실물 하드웨어 시험은 별도 안전 승인을 받습니다.

현재 암 동작 및 NOMI Manipulation Skill 통합은 완료되지 않았습니다.
