# 테스트 결과

## 이전 검증 기록(사용자 제공)
| 시험 | 결과 | 비고 |
|---|---|---|
| 실제 웹 UI LLM 비이동 A–E | PASS로 보고됨 | 상태 질의, 모델 질의, 목적지 조회, 모호한 이동 확인 질문, 검증 전용 목적지 인자 검사 |
| E 목적지 Tool 인자 검사 | PASS로 보고됨 | 실제 이동 Skill 호출 및 /nomi/navigation_request 발행을 하지 않은 안전 경로 |
| 별도 MuJoCo 테이블 1 주행 | 성공으로 보고됨 | 비이동 LLM UI 시험과 별개 |
| 별도 MuJoCo 테이블 3 주행 | 성공으로 보고됨 | 비이동 LLM UI 시험과 별개 |
| 실물 로봇 | 미검증 | 이번 작업에서 사용하지 않음 |
| LLM 자연어를 통한 실제 자동 주행 종단 검증 | 미검증 | 비이동 E 및 UI 경로 주행과 구분 |
| 로봇암 학습/추론/제어 연결 | 미검증 | 팀원 모듈 미연결 |
| gripper 실제 완료 피드백 | 미검증 | 기존 Skill은 ROS 발행 결과까지만 확인 |

이 결과들은 사용자 대화에서 제공된 기록이며 이번 전달 패키지 작업에서 다시 실행하지 않았습니다. 테스트 로그 파일은 해당 경로에서 확인되지 않아 새로운 로그나 수치를 만들지 않았습니다.

## 이번 전달 패키지 자체 검사
복사 후 원본 파일 해시 비교, Python AST 문법 확인, ROS package.xml 파싱, MuJoCo XML 참조 경로 검사는 감사 기록에 기재됩니다. 실행 중 서비스나 ROS 노드는 재시작·중지하지 않았습니다. UI production build는 node_modules를 제외했으므로 재설치 후 별도 수행이 필요합니다.

## GitHub 준비 사본에서 다시 실행한 검사 (2026-10-21)
| 검사 | 결과 | 비고 |
|---|---|---|
| ROS 2 colcon 빌드 | PASS | 복사한 ros2_ws에서 nomi_agent, nomi_xlerobot_sim, nomi_rviz_bridge 3개 패키지 빌드 |
| Python AST 문법 검사 | PASS | Python 파일 82개, 구문 오류 0개 |
| 웹 TypeScript 및 Vite production build | PASS | 복사본에서 수행; 검증을 위해 기존 node_modules를 읽기 전용 참조로 사용 |
| XML 및 MuJoCo mesh/include 경로 | PASS | XML 5개 파싱, 실제 mesh/include 경로 누락 0개 |
| NOMI Agent pytest | PARTIAL | 75 passed, 6 skipped, 1 failed. 실패는 테스트 Python 환경에 ollama 모듈이 없어 Native Tool Protocol 테스트가 import되지 않은 환경 의존 문제 |
| MuJoCo Host ZMQ pytest | NOT RUN | 통합 pytest 수집 시 현재 Python 환경에 mujoco 모듈이 없어 수집 실패. MuJoCo 패키지를 설치하지 않았음 |
| 실제 Ollama 추론·MuJoCo 이동 | NOT RUN | 이 준비 작업에서는 수행하지 않음 |

ROS 빌드 및 프런트 빌드는 통과했지만, 위 테스트 결과만으로 새 컴퓨터에서의 전체 설치·실행을 보증하지 않습니다. 빠진 Python 의존성은 설치 문서의 패키지 설치 단계에서 준비한 뒤 테스트해야 합니다.
