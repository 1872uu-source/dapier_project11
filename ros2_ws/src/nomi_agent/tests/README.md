# NOMI Function/Tool Harness 테스트

## 오프라인 회귀 테스트

ROS 2 노드나 실제 로봇 없이 표준 `unittest`로 실행합니다. 테스트는 Mock LLM과 Mock Robot을 사용하며, 외부 HTTP 응답도 가짜 응답으로 대체합니다.

```bash
source ~/venvs/xlerobot_mujoco/bin/activate
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=~/ros2_ws/src/nomi_agent \
  python ~/ros2_ws/src/nomi_agent/tests/run_evaluation.py
```

JSONL 감사 로그는 기본적으로 `/tmp/nomi-agent-test-logs/` 아래에 저장됩니다. 경로를 바꾸려면 `NOMI_TEST_LOG_DIR`을 지정합니다.

## 선택적 실제 LLM 라우팅 테스트

실제 모델은 도구를 호출하지 않고 자연어를 도구 계획으로 분류하는 단계만 평가합니다. 현재 설정된 프로필과 자격 증명이 필요하며, 호출 비용이나 지연이 발생할 수 있습니다.

```bash
NOMI_LIVE_LLM=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=~/ros2_ws/src/nomi_agent \
  python -m unittest discover -s ~/ros2_ws/src/nomi_agent/tests -p 'test_live_llm_optional.py' -v
```

## ROS 2 그래프 통합 테스트

먼저 Jazzy, 빌드된 overlay, 가상환경 순서로 환경을 적용합니다. 전용 ROS domain(기본 222)을 사용하고, LLM 및 스킬을 Mock으로 교체한 뒤 `/nomi/command`와 `/nomi/cancel`만 발행합니다. MuJoCo 호스트와 실제 이동 토픽은 실행하지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/venvs/xlerobot_mujoco/bin/activate
export PYTHONPATH=~/ros2_ws/install/nomi_agent/lib/python3.12/site-packages:~/ros2_ws/install/nomi_xlerobot_sim/lib/python3.12/site-packages:~/ros2_ws/src/nomi_agent${PYTHONPATH:+:$PYTHONPATH}
NOMI_ROS_TEST=1 NOMI_ROS_TEST_DOMAIN_ID=222 NOMI_MODEL_PROFILE=qwen_hermes \
  python -m unittest tests.test_ros2_safe_integration -v
```

`ROS_LOG_DIR` 기본값은 `/tmp/nomi-ros-test-logs`입니다. 실제 모델 호출은 하지 않습니다.

Mock 시나리오의 제안 기준은 고정 입력에서 예상 도구 선택·유효 인자 전달·다단계 순서 준수·실패 후속 단계 차단·잘못된 호출 차단·타임아웃 및 취소 판정 각각 100%입니다. 실제 LLM 기준은 20개 한국어 명령으로 라우팅 정확도 90% 이상을 제안하되, 사용자 승인 후 확정합니다. 실제 LLM의 도구 실행 정확도는 별도 실행 어댑터 통합 전까지 이 테스트 결과에 포함하지 않습니다.

## 모델 프로필 선택 및 Mock 벤치마크

기존 `qwen_hermes` 프로필은 유지됩니다. 새 단일 모델 프로필은 `NOMI_MODEL_PROFILE=qwen35_single`로 선택하며 기본 모델은 `qwen3.5:9b`입니다. `NOMI_SINGLE_MODEL`로 다른 Ollama 모델명을 지정할 수 있습니다. 단일 모델은 별도 Router 요청 없이 ToolRegistry의 실제 스키마를 첫 모델 요청부터 받습니다. 후속 도구 선택이 실행 결과에 의존하면 같은 모델이 추가 요청을 하므로, 복합 작업은 호출 횟수가 1회보다 클 수 있습니다.

단일 모델의 대화는 XML이 아닌 Ollama Native 형식의 assistant `tool_calls`와 `role=tool`/`tool_name` 메시지를 사용합니다. Ollama 0.33.3 SDK에는 `tool_call_id` 필드가 없어 NOMI가 요청·라운드별 ID를 생성하거나 응답 ID를 보존하고, 해당 ID를 도구 결과 본문에 넣어 호출과 결과를 연결합니다. 기존 Hermes 경로는 XML 변환을 유지합니다.

동일한 12개 한국어 요청을 두 프로필에 각각 보내는 벤치마크입니다. 실제 모델은 호출하지만, 로봇 기능은 전부 Mock으로 대체하므로 ROS 노드·MuJoCo·모터·이동 토픽을 구동하지 않습니다. Ollama에 `qwen2.5:7b`, `hermes3:8b`, `qwen3.5:9b`가 설치되어 있어야 합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/venvs/xlerobot_mujoco/bin/activate
cd ~/ros2_ws/src/nomi_agent
python -m tests.benchmark_profiles --repeats 2 \
  --output ~/XLeRobot/nomi_benchmarks/profile_comparison.csv
```

CSV에는 명령별 예상·실제 도구, 정확도, Harness 전체 지연시간, 모델 요청 수, 실패 여부를 기록합니다. 실행 환경에서 Ollama 또는 필요한 모델을 찾지 못하면 측정값 대신 `UNAVAILABLE` 행과 원인을 기록합니다. 두 호출 구성에서 Qwen Router와 Hermes Worker 요청은 각각 모델 호출 1회로 집계하고, 단일 프로필은 Qwen의 실제 요청 수를 집계합니다.
