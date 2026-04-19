# OpenAI BEV Driving Logic

## 1. 목적

이 시스템은 Isaac Sim 환경에서 RGB, Depth, BEV(Bird's-Eye View), IMU, 선택적 Odom 정보를 사용해 로봇의 다음 주행 명령을 생성하는 `LLM-assisted local navigation` 파이프라인이다.

현재 설계 목표는 다음과 같다.

- `BEV`를 중심으로 비통과 장애물을 보수적으로 해석한다.
- `global goal`은 장기 목적지로 유지하되, 매 step은 `local goal`과 `route plan`을 통해 부드럽게 갱신한다.
- LLM은 단순 수치 제어기라기보다 `의도(intent)`와 `단기 계획(commitment)`을 생성하는 상위 정책으로 사용한다.
- 실제 충돌 방지와 명령 안정화는 후단 deterministic safety layer가 담당한다.

메인 구현 파일은 [openai_bev_autodrive.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py) 이다.

## 2. 시스템 구성

구성은 크게 5계층으로 나뉜다.

1. `Perception`
2. `State / Memory`
3. `LLM Planning`
4. `Command Sanitization`
5. `Execution / Logging / Dashboard`

상위 수준 데이터 흐름은 아래와 같다.

```text
RGB/Depth/BEV/IMU/Odom
    -> PerceptionSnapshot
    -> goal state / route plan / planner hint / memory summary
    -> prompt + attached images
    -> OpenAI structured output
    -> local waypoint + cmd_vel hint
    -> deterministic safety / smoothing / wall handling
    -> cmd_vel publish
    -> execution history / prompt-response logs / dashboard
```

## 3. 좌표계와 기본 수학

현재 코드의 로봇 기준 좌표는 다음을 사용한다.

- `+x`: robot-right
- `+z` 또는 `forward`: robot-forward
- BEV의 원점: 로봇 현재 위치
- BEV 위쪽: 로봇 현재 전방

좌표 변환 핵심 함수는 [openai_bev_autodrive.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L283) 부근에 있다.

```python
def world_to_robot(delta_x, delta_y, yaw):
    robot_right = delta_x * sin(yaw) - delta_y * cos(yaw)
    robot_forward = delta_x * cos(yaw) + delta_y * sin(yaw)

def robot_to_world(robot_right, robot_forward, yaw):
    delta_x = robot_forward * cos(yaw) + robot_right * sin(yaw)
    delta_y = robot_forward * sin(yaw) - robot_right * cos(yaw)
```

즉 `global goal`은 world 좌표로 유지되고, 실제 planning 시에는 매 step 현재 pose 기준 `robot-right / robot-forward`로 다시 투영된다.

## 4. 핵심 상태와 메모리

노드 초기화는 [OpenAIDriveNode.__init__](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L448)에 있다.

주요 상태는 다음과 같다.

- 센서 최신 프레임
  - `rgb_bgr`
  - `depth_vis`
  - `camera_info`
- pose 관련
  - `current_pose`
  - `odom_position_pose`
  - `odom_reported_yaw`
  - `imu_raw_yaw`
  - `imu_aligned_yaw`
  - `imu_gyro_integrated_yaw`
  - `cmd_yaw_estimate`
- goal 관련
  - `goal_input_x`, `goal_input_y`
  - `goal_x`, `goal_y`
  - `goal_anchor_pose`
  - `local_goal_world_x`, `local_goal_world_y`
- planning / execution 관련
  - `execution_queue`
  - `active_execution`
  - `command_history`
- route plan 관련
  - `route_plan_mode`
  - `route_plan_sign`
  - `route_plan_reason`
  - `route_plan_hold_until_step`
- obstacle memory
  - `world_obstacle_memory`

메모리 윈도우 크기는 파일 상단 상수로 정의되어 있다. [openai_bev_autodrive.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L42)

- `HISTORY_WINDOW = 24`
- `PREVIOUS_CONTEXT_WINDOW = 12`
- `PREVIOUS_BEV_IMAGE_WINDOW = 6`
- `PREVIOUS_RGB_IMAGE_WINDOW = 2`

즉 시스템은 단일 프레임 reactive driver가 아니라, 최근 수십 step의 행동/결과를 계속 누적하는 구조다.

## 5. 입력 센서 사용 방식

### 5.1 BEV

가장 중요한 입력이다.

- red points: 비통과 장애물
- red shadow / filled region: 장애물 뒤쪽의 blocked or unknown 영역
- cyan ego circle: 로봇 footprint

시스템 프롬프트도 `RGB/Depth보다 BEV를 우선`하도록 강하게 묶여 있다. [SYSTEM_PROMPT](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L51)

### 5.2 RGB / Depth

보조 참조 역할이다.

- RGB: semantic context
- Depth: near/far 보조
- 하지만 red BEV obstacle geometry를 override하지 못한다

### 5.3 IMU / Odom / cmd_vel dead reckoning

pose는 단일 소스가 아니라 조합형이다.

- 위치는 `odom` 또는 `cmd_vel` dead reckoning
- yaw는 `imu`, `odom`, `cmd_vel`, `hybrid`
- `pose_diagnostics`로 각 yaw 소스 차이를 계속 기록한다

현재 파서 기본값은 [build_arg_parser](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L5640) 부근 기준으로:

- `goal-frame = start_local`
- `pose-source = imu_cmd_vel`
- `yaw-source = hybrid`
- `control-mode = direct_cmd_vel`

## 6. Goal 계층

이 시스템은 목표를 3계층으로 본다.

### 6.1 Global Goal

최종 목적지다.

- 입력은 `--goal-frame start_local` 또는 `--goal-frame world`
- 내부적으로는 world 기준으로 유지
- planning 시에는 매 step 현재 pose 기준 local로 다시 변환

핵심 함수:

- [compute_global_goal_local](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1163)
- [compute_goal_local](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1208)

### 6.2 Local Goal

현재 몇 step 동안 유지할 중간 목표다.

역할:

- global goal을 바로 greedy하게 쫓지 않도록 완충
- corridor continuity 유지
- blocked wall 앞에서 detour continuation 제공

핵심 함수:

- [planning_reference_local_tuple](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1215)
- [local_goal_needs_refresh](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1241)
- [choose_local_goal_candidate](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1360)

### 6.3 Route Plan

`local goal`보다 더 추상적인 단기 계획 상태다.

예:

- `startup-explore`
- `around_wall`
- `agent-scan`
- `agent-detour`
- `agent-explore`

즉 route plan은 `이번엔 왼쪽으로 돌아간다`, `초반엔 살짝 탐색한다` 같은 단기 전략 메모리다.

핵심 함수:

- [apply_agent_plan_commitment](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L2290)
- [update_route_plan_state](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L2378)

## 7. Planner Hint 생성

LLM 입력 전에 deterministic planner hint를 먼저 만든다. 함수는 [build_planner_hint](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L2026) 이다.

이 단계에서 만드는 candidate 예시는 다음과 같다.

- `direct`
- `corridor-center`
- `left-detour`
- `right-detour`
- `continue-stream`
- `queue-head`
- `startup-explore`

각 candidate는 다음 요소로 점수화된다.

- progress score
- continuation bonus
- clearance bonus
- lateral penalty
- turn penalty
- soft clearance penalty
- corridor center penalty
- blocked penalty
- short penalty
- continuity bonus / penalty
- commitment bonus

이 단계가 중요한 이유는 LLM이 완전히 맨땅에서 생각하는 게 아니라, 시스템이 먼저 `가능한 좋은 local geometry 후보`를 만들어서 컨텍스트로 제공하기 때문이다.

## 8. Route Plan 상태기계

`update_route_plan_state()`는 blocked wall이나 초기 불확실성에 대응하는 상위 상태기계다. [openai_bev_autodrive.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L2378)

현재 핵심 분기:

- `startup-explore`
  - 시작 몇 step 동안 corridor가 불확실하면 탐색 우선
- `around_wall`
  - direct progress가 벽에 막히면 detour side를 정하고 몇 step 유지

여기에 더해 LLM이 명시적으로 낸 의도도 route plan으로 승격될 수 있다.

- `scan_left/right` -> `agent-scan`
- `detour_left/right` -> `agent-detour`
- `explore` -> `agent-explore`

이렇게 해서 `한 프레임짜리 반사 반응`이 아니라 `짧게 유지되는 계획`이 생긴다.

## 9. LLM 출력 스키마

LLM 출력은 자유 텍스트가 아니라 [DriveCommand](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L253) 스키마로 강제된다.

핵심 필드:

- `nav_mode`
  - `progress`
  - `detour_left`
  - `detour_right`
  - `scan_left`
  - `scan_right`
  - `reverse_escape`
  - `explore`
- `agent_phase`
  - `advance`
  - `detour`
  - `scan`
  - `recover`
- `observation_target`
  - `front_corridor`
  - `left_opening`
  - `right_opening`
  - `wall_edge`
  - `goal_sector`
- `plan_commit_steps`
- `speed_band`
- `turn_band`
- `duration_band`
- `waypoint_*`
- `linear_mps`, `angular_radps`, `duration_s`

즉 현재 LLM은 단순 `[v, w, t]` 모델이 아니라 아래 순서를 따라야 한다.

1. 지금 phase가 무엇인지 정함
2. 뭘 관찰/탐색하려는지 정함
3. 몇 step commit할지 정함
4. band 단위 속도/회전/지속시간 정함
5. waypoint와 numeric command를 일관되게 채움

## 10. 프롬프트 구조

프롬프트 빌더는 두 종류가 있다.

- [build_prompt_text](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L2714)
- [build_compact_prompt_text](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L3059)

프롬프트에는 아래 정보가 들어간다.

- 현재 pose
- goal frame
- global goal local/world
- active local goal
- 현재 cmd / 현재 waypoint
- obstacle sectors / corridor summary
- persistent obstacle memory
- planner hint 후보들
- route plan 상태
- history summary
- trajectory tail
- previous step 결과
- pose diagnostics
- safety caps

즉 LLM은 현재 프레임만 보는 게 아니라 `단기 주행 히스토리 + 현재 corridor + 상위 route plan`을 함께 본다.

## 11. 이미지 입력 구성

API 입력 조립은 [build_api_content](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L3145) 에 있다.

항상 들어가는 이미지:

- current RGB
- current depth vis
- current BEV

추가로 들어갈 수 있는 이미지:

- previous BEV 최대 6장
- previous RGB 최대 2장

의도는 명확하다.

- 이전 BEV: obstacle memory
- 이전 RGB: corridor shape / opening memory

즉 slight scan turn 후에도 “조금 전 왼쪽에 복도 입구가 있었다” 같은 문맥을 유지하려는 구조다.

## 12. OpenAI 호출과 재시도

LLM 호출은 [request_drive_command](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L3207) 에 있다.

주요 특징:

- `responses.parse` 사용
- `DriveCommand`로 structured parsing
- reasoning effort와 max token을 달리하는 다단 retry

시도 순서:

1. full prompt + previous BEV 포함
2. 더 큰 token budget
3. compact prompt + 더 큰 token budget

즉 context가 길어도 parse 실패를 줄이기 위한 재시도 구조를 이미 갖고 있다.

## 13. Command 생성 계층

실제 명령 생성은 [sanitize_command](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L3444) 부터 시작한다.

고수준 흐름은 아래와 같다.

```text
LLM output
  -> sanitize_local_waypoint()
  -> direct_command_from_model() or waypoint_to_command()
  -> front / side / goal / memory / reverse-escape / rate-limit gating
  -> final cmd_vel
```

즉 sanitize 단계가 실질적인 후단 제어기 역할을 한다.

## 14. direct_cmd_vel 모드

현재 기본 `control-mode`는 `direct_cmd_vel`이다. [build_arg_parser](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L5680)

하지만 이름만 direct일 뿐, 완전 raw passthrough는 아니다.

- LLM numeric command 사용
- 동시에 `nav_mode`, `speed_band`, `turn_band`, `duration_band`도 해석
- 둘을 blend한 후 safety layer를 통과

핵심 함수:

- [direct_command_from_model](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L3703)
- [profile_command_from_model](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4070)

예를 들어:

- `scan_left`면 느린 전진 + 좌회전
- `scan_right`면 느린 전진 + 우회전
- `detour_left/right`면 전진 + 해당 방향 arc
- `reverse_escape`면 후진 기반 recovery

## 15. Waypoint 정제 계층

LLM이 잘못된 waypoint를 내도 그대로 쓰지 않는다. 정제는 [sanitize_local_waypoint](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4257) 에서 수행한다.

수행 내용:

- non-finite 값 교정
- corridor bounds clamp
- corridor center bias
- side-wall escape bias
- front clearance 기반 forward cap
- red-point blocked path 검사
- body footprint 고려한 hard block margin 적용
- fully blocked면 exploration waypoint 선택

즉 waypoint는 LLM suggestion이지 final truth가 아니다.

## 16. Safety 로직

현재 안전 로직은 상당히 두껍다. 주요 항목:

- `front-clearance-blocked-forward`
- `goal-behind-soft-reorient`
- `prefer-1m-clearance-detour`
- `preserve-recent-detour-memory`
- `goal-ahead-add-forward-progress`
- `goal-ahead-limit-turn-rate`
- `maintain-safe-forward-progress`
- `final-rate-limit`
- `reverse-escape-from-wall`
- `global-goal-reached-stop`

핵심 의도는 다음과 같다.

- 벽 앞에서 무리한 전진 금지
- 최근 detour를 바로 뒤집지 않음
- goal이 앞이면 괜한 회전 억제
- 완전히 막히면 후진-회전 recovery 허용
- 연속 명령은 급격히 변하지 않게 rate limit

## 17. Robot footprint 모델

현재 로봇은 점이 아니라 body로 취급한다.

관련 함수:

- [robot_radius_m](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4118)
- [robot_body_safety_buffer_m](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4121)
- [robot_hard_block_margin](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4124)
- [robot_preferred_center_clearance](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4127)
- [robot_front_stop_clearance](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4134)
- [robot_side_escape_clearance](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4137)

즉 collision 판단은 centerline만 보는 게 아니라

`robot_radius + body_safety_buffer + extra hard margin`

기준으로 이뤄진다.

## 18. Exploration 로직

“길을 모르겠을 때”를 위한 exploration은 deterministic layer에도 있고, LLM schema에도 있다.

deterministic:

- `startup-explore`
- `around_wall`
- [choose_exploration_waypoint](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L4170)

LLM:

- `scan_left`
- `scan_right`
- `explore`
- `observation_target`
- `plan_commit_steps`

즉 현재 구조는 “회전도 유효한 탐색 액션”으로 취급한다.

## 19. 현재 회전 정책의 상태

중요한 점 하나는, 예전에 넣었던 강한 `heading alignment`는 현재 사실상 비활성화된 상태라는 점이다.

즉 지금은:

- hard rotate-first mode를 강하게 강제하지 않음
- 대신 `soft reorient + scan/explore + route plan memory`로 해결하려고 함

이건 “뒤에 있는 goal 때문에 rigid rotate-only 상태에 빠지는 것”을 줄이기 위한 설계 선택이다.

## 20. Goal complete

goal complete는 `global goal distance` 기준이다.

관련 함수:

- [maybe_mark_goal_complete](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L1633)

기본값:

- `--goal-complete-distance = 1.0`

즉 local goal 도달이 아니라 global goal 반경 진입이 완료 조건이다.

## 21. 메인 루프

메인 루프는 파일 하단 [main](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L5718) 에 있다.

루프는 반복적으로 다음을 한다.

1. ROS spin
2. planning result poll
3. 필요 시 새 planning request launch
4. dashboard render
5. keyboard input 처리

즉 planning thread와 실행 loop가 완전히 같은 타이밍으로 묶인 단순 synchronous 구조는 아니다.

## 22. 디버깅 산출물

세션 폴더에는 step별로 아래 파일들이 저장된다.

- `step_XXXX_rgb.png`
- `step_XXXX_depth.png`
- `step_XXXX_bev.png`
- `step_XXXX_dashboard.png`
- `step_XXXX.json`
- `step_XXXX_prompt.md`
- `step_XXXX_response.md`
- `session.jsonl`

이 중 디버깅 핵심은 다음이다.

- `prompt.md`
  - 실제 모델이 본 텍스트 컨텍스트
- `response.md`
  - 실제 structured output과 적용 결과
- `step.json`
  - goal state, obstacle metrics, route plan, planner hint, pose diagnostics

## 23. 현재 기본 파라미터

주요 기본값은 [build_arg_parser](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py#L5640) 이후에 정의되어 있다.

중요한 값:

- `model = gpt-5.4-nano`
- `control-mode = direct_cmd_vel`
- `inference-hz = 10.0`
- `max-linear = 1.15`
- `max-angular = 0.45`
- `max-duration = 3.6`
- `min-motion-duration = 1.8`
- `memory-horizon-s = 20.0`
- `memory-range-m = 10.0`
- `detour-commit-s = 4.5`
- `robot-radius = 0.35`
- `body-safety-buffer = 0.18`
- `desired-clearance = 1.0`

## 24. 현재 구조의 해석

기술적으로 현재 시스템은 다음 중간 지점에 있다.

- 완전 classical local planner: 아님
- 완전 direct VLM driver: 아님
- 완전 SLAM global planner: 아님

가장 정확한 표현은:

`short-memory agentic local navigator with deterministic safety enforcement`

즉:

- LLM은 상위 의도와 corridor choice를 담당
- deterministic layer는 충돌 회피와 명령 안정화를 담당
- memory는 local map의 대체물이 아니라 `단기 구조 기억` 역할을 한다

## 25. 현재 설계의 강점과 한계

### 강점

- BEV obstacle 우선 해석
- robot footprint 고려
- prompt/response/debug artifact가 잘 남음
- route plan과 history가 있어서 완전 프레임 독립 반응보다 낫다
- exploration, scan, detour를 명시적 action으로 다룬다

### 한계

- 장기 전역 지도 기반 path planning은 아님
- IMU/cmd_vel dead reckoning drift 가능
- red-point quality와 BEV inflation 품질에 크게 의존
- LLM이 여전히 local greedy bias를 보일 수 있음
- safety layer가 두꺼워질수록 보수적/불안정 상호작용이 생길 수 있음

## 26. 요약

현재 드라이빙 로직의 핵심은 아래 한 문장으로 정리할 수 있다.

> `global goal`은 장기 방향성만 제공하고, 실제 주행은 `local goal + route plan + short-term visual memory + BEV obstacle map`을 기반으로 LLM이 상위 의도를 정하고, deterministic safety layer가 최종 `cmd_vel`을 보정하는 구조다.

이 구조를 이해할 때 가장 중요한 파일은 두 개다.

- [openai_bev_autodrive.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/openai_bev_autodrive.py)
- [rgb_depth_bev_current.py](/home/data1/isaac_sim_ros/python_codes/Autonomous_Drive/rgb_depth_bev_current.py)

그리고 실제 디버깅은 세션 폴더의 `step_XXXX_prompt.md`, `step_XXXX_response.md`, `step_XXXX.json`을 같이 보는 것이 가장 빠르다.
