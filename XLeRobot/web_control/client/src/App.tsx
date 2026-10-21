import { useEffect, useRef, useState } from 'react';
import { Moon, Sun, Radio, Activity, Bot, Compass, Cpu, Gauge, Gamepad2, MessageCircle, SlidersHorizontal } from 'lucide-react';
import { useSocket } from './hooks/useSocket';
import { GameSimulationCanvas } from './components/features/GameSimulationCanvas';
import { GameControlDeck } from './components/features/GameControlDeck';
import { DestinationNavigator, type Destination } from './components/features/DestinationNavigator';
import { NomiPanel } from './components/features/NomiPanel';
import type { RobotSimulationState } from './types';
import { findRoute, getDynamicObstaclePoints, isRouteBlockedByDynamicObstacle, type RoutePoint } from './utils/pathPlanner';
import { INDOOR_MAP, NAVIGATION_DESTINATIONS } from './utils/indoorMap';
import { computeWaypointCommand, NavigationMotionGuard, shouldStopForDriveFeedback } from './utils/navigationController';

type StickVector = { x: number; y: number };

function readSavedHome(): Destination | null {
  try {
    const saved = localStorage.getItem('xlerobot.homeWaypoint');
    if (saved) {
      const value = JSON.parse(saved) as Destination;
      if (Number.isFinite(value.x) && Number.isFinite(value.y)
        && value.x >= -18 && value.x <= 18 && value.y >= -4 && value.y <= 24) {
        return { name: '집', x: value.x, y: value.y };
      }
    }
  } catch {
    // Use the built-in home waypoint when browser storage is unavailable.
  }
  return null;
}

function readSavedDestinations(): Destination[] {
  try {
    const saved = localStorage.getItem('xlerobot.savedDestinations');
    if (!saved) return [];
    const values = JSON.parse(saved) as unknown;
    if (!Array.isArray(values)) return [];
    return values.filter((value): value is Destination => value && typeof value.name === 'string'
      && value.name.trim().length > 0 && Number.isFinite(value.x) && Number.isFinite(value.y)
      && value.x >= -18 && value.x <= 18 && value.y >= -4 && value.y <= 24)
      .map(value => ({ name: value.name.trim(), x: value.x, y: value.y }));
  } catch {
    return [];
  }
}

function numberText(value: number | undefined) {
  return Number.isFinite(value) ? (value as number).toFixed(2) : '0.00';
}

function RobotTelemetry({
  state,
  localPose,
  speed,
  moving,
  socketStatus,
}: {
  state: RobotSimulationState | null;
  localPose: { x: number; y: number; yaw: number };
  speed: number;
  moving: boolean;
  socketStatus: string;
}) {
  const x = state?.position?.x ?? localPose.x;
  const y = state?.position?.y ?? localPose.y;
  const yaw = state?.rotation?.yaw ?? localPose.yaw;
  const left = state?.arm_joints?.left ?? [];
  const right = state?.arm_joints?.right ?? [];
  const source = state?.host_connected ? 'MUJOCO LIVE' : socketStatus === 'connected' ? 'HOST WAITING' : 'LOCAL SIM';

  return (
    <section className="surface-card rounded-2xl border p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-bold tracking-[0.24em] text-slate-500">로봇 상태</div>
          <h2 className="mt-1 text-base font-semibold">시뮬레이션 상태</h2>
        </div>
        <span className="rounded-full bg-blue-50 px-2.5 py-1 font-mono text-[9px] tracking-widest text-blue-700">{source}</span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="surface-subcard rounded-xl border p-3">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-500"><Compass size={12} /> X 위치</div>
          <div className="mt-2 font-mono text-xl text-[var(--ui-fg)]">{numberText(x)}<span className="ml-1 text-xs text-slate-500">m</span></div>
        </div>
        <div className="surface-subcard rounded-xl border p-3">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-500"><Compass size={12} /> Y 위치</div>
          <div className="mt-2 font-mono text-xl text-[var(--ui-fg)]">{numberText(y)}<span className="ml-1 text-xs text-slate-500">m</span></div>
        </div>
        <div className="surface-subcard rounded-xl border p-3">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-500"><Gauge size={12} /> 주행 속도</div>
          <div className="mt-2 flex items-center gap-2 font-mono text-xl text-blue-600">{speed.toFixed(2)}<span className="text-xs text-slate-500">×</span><span className={`ml-auto h-2 w-2 rounded-full ${moving ? 'animate-pulse bg-emerald-400' : 'bg-slate-700'}`} /></div>
        </div>
        <div className="surface-subcard rounded-xl border p-3">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-500"><Activity size={12} /> 방향</div>
          <div className="mt-2 font-mono text-xl text-[var(--ui-fg)]">{((yaw * 180 / Math.PI + 360) % 360).toFixed(0)}<span className="ml-1 text-xs text-slate-500">°</span></div>
        </div>
      </div>

      <div className="mt-4 surface-subcard rounded-xl border p-3">
        <div className="mb-2 flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-500"><Bot size={12} /> 팔 관절 <span className="ml-auto text-slate-600">RAD</span></div>
        <div className="grid grid-cols-2 gap-3">
          {[['왼팔', left], ['오른팔', right]].map(([label, values]) => (
            <div key={label as string}>
              <div className="mb-1 text-[9px] font-bold tracking-widest text-blue-600/80">{label as string}</div>
              <div className="space-y-1">
                {(values as number[]).slice(0, 6).map((angle, index) => (
                  <div key={index} className="flex items-center justify-between font-mono text-[10px] text-[var(--ui-muted)]"><span>J{index + 1}</span><span>{numberText(angle)}</span></div>
                ))}
                {(values as number[]).length === 0 && <div className="font-mono text-[10px] text-[var(--ui-muted)]">데이터 대기 중</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function App() {
  const [speed, setSpeed] = useState(1.0);
  const {
    socket,
    status,
    sendPing,
    sendMoveCommand,
    sendDriveCommand,
    simulationState,
    commandFeedback,
    nomiNavigationRequest,
    nomiNavigationCancel,
    pressedKeys,
    stopContinuousMovement,
    sendNomiNavigationResult,
  } = useSocket(speed);

  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [mobilePanel, setMobilePanel] = useState<'drive' | 'nomi' | 'status'>('drive');
  const [joystick, setJoystick] = useState<StickVector>({ x: 0, y: 0 });
  const [controlDirection, setControlDirection] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const [localPose, setLocalPose] = useState({ x: 0, y: 0, yaw: 0 });
  const [homeWaypoint, setHomeWaypoint] = useState<Destination | null>(readSavedHome);
  const [savedDestinations, setSavedDestinations] = useState<Destination[]>(readSavedDestinations);
  const [destination, setDestination] = useState<Destination>(() => readSavedHome()
    ?? readSavedDestinations().find(place => place.name.normalize('NFKC').trim().toLocaleLowerCase() === '집')
    ?? { name: '', x: Number.NaN, y: Number.NaN });
  const [navigationStatus, setNavigationStatus] = useState<'idle' | 'navigating' | 'arrived' | 'stopped' | 'blocked'>('idle');
  const [plannedRoute, setPlannedRoute] = useState<RoutePoint[]>([]);
  const [routeOrigin, setRouteOrigin] = useState<RoutePoint | null>(null);
  const [waypointIndex, setWaypointIndex] = useState(0);
  const [navigationNotice, setNavigationNotice] = useState<string | null>(null);
  const turnDirectionRef = useRef<number | null>(null);
  const motionGuardRef = useRef(new NavigationMotionGuard());
  const lastControllerPhaseRef = useRef<string | null>(null);
  const lastHandledDriveFeedbackSequenceRef = useRef(0);
  const activeNomiNavigationRef = useRef<string | null>(null);
  const logNavigation = (event: string, details: Record<string, unknown> = {}) => {
    console.info('[navigation]', JSON.stringify({
      event,
      host_connected: simulationState?.host_connected ?? false,
      state_age: simulationState?.state_age ?? null,
      scan_healthy: simulationState?.obstacle_scan_status?.healthy ?? false,
      scan_age_ms: simulationState?.obstacle_scan_status?.age_ms ?? null,
      navigation_available: navigationAvailable,
      navigation_unavailable_reason: navigationUnavailableReason,
      ...details,
    }));
  };
  const clearPlannedRoute = (reason: string, details: Record<string, unknown> = {}) => {
    if (plannedRoute.length > 0) logNavigation('route_cleared', { reason, waypoint_count: plannedRoute.length, ...details });
    setPlannedRoute([]);
  };
  const reportNomiNavigationResult = (
    status: 'SUCCEEDED' | 'FAILED' | 'CANCELLED',
    message: string,
    pose?: RoutePoint,
    distance?: number,
  ) => {
    const requestId = activeNomiNavigationRef.current;
    if (!requestId) return;
    const verifiedArrival = status === 'SUCCEEDED' && pose && Number.isFinite(distance) && distance! <= 0.3;
    const sent = sendNomiNavigationResult({
      request_id: requestId,
      status,
      message,
      ...(verifiedArrival ? { completion_verified: true, position: pose, distance_m: distance } : {}),
    });
    logNavigation('nomi_navigation_result', {
      request_id: requestId,
      status: verifiedArrival ? 'SUCCEEDED' : status === 'SUCCEEDED' ? 'FAILED' : status,
      completion_verified: Boolean(verifiedArrival && sent),
      distance_m: distance ?? null,
      delivered: sent,
      message,
    });
    activeNomiNavigationRef.current = null;
  };
  const navigationEffectsRef = useRef({ clearPlannedRoute, reportNomiNavigationResult });
  navigationEffectsRef.current = { clearPlannedRoute, reportNomiNavigationResult };
  const handledNomiRequestRef = useRef<string | number | null>(null);
  const lastJoystickCommandRef = useRef(0);
  const hostPosition = simulationState?.position;
  const hostYaw = simulationState?.rotation?.yaw;
  const stateAge = simulationState?.state_age;
  const explicitMujocoMode = simulationState?.robot_type === 'mujoco'
    && simulationState?.navigation_execution_enabled === true
    && simulationState?.nomi_mock_mode !== true;
  const hostStateAvailable = status.socket === 'connected'
    && simulationState?.host_connected === true
    && Number.isFinite(stateAge) && (stateAge as number) <= 2.5
    && Number.isFinite(hostPosition?.x) && Number.isFinite(hostPosition?.y)
    && Number.isFinite(hostYaw);
  const hostPositionFresh = status.socket === 'connected'
    && simulationState?.host_connected === true
    && Number.isFinite(stateAge) && (stateAge as number) <= 2.5
    && Number.isFinite(hostPosition?.x) && Number.isFinite(hostPosition?.y);
  const scanStatus = simulationState?.obstacle_scan_status;
  const rangeSensorAvailable = scanStatus?.healthy === true
    && Number.isFinite(scanStatus.age_ms) && (scanStatus.age_ms as number) <= 1200
    && Array.isArray(simulationState?.obstacle_scan);
  const navigationAvailable = explicitMujocoMode && hostStateAvailable && rangeSensorAvailable;
  let navigationUnavailableReason: string | null = null;
  if (status.socket !== 'connected') {
    navigationUnavailableReason = '웹 서버와 연결되지 않았습니다.';
  } else if (simulationState?.nomi_mock_mode === true) {
    navigationUnavailableReason = 'Mock Agent 모드는 MuJoCo와 실제 로봇 주행을 차단합니다.';
  } else if (!simulationState) {
    navigationUnavailableReason = 'MuJoCo 상태 데이터가 아직 도착하지 않았습니다.';
  } else if (simulationState.robot_type !== 'mujoco') {
    navigationUnavailableReason = '목적지 주행은 명시적으로 MuJoCo 모드가 확인된 경우에만 허용됩니다.';
  } else if (simulationState.host_connected !== true) {
    navigationUnavailableReason = 'MuJoCo 호스트가 연결되지 않았습니다. MuJoCo 호스트를 실행하고 연결을 확인하세요.';
  } else if (simulationState.navigation_execution_enabled !== true) {
    navigationUnavailableReason = 'MuJoCo 목적지 주행이 비활성화되어 있습니다. NOMI_MUJOCO_NAV_ENABLED=1 설정이 필요합니다.';
  } else if (!Number.isFinite(stateAge)) {
    navigationUnavailableReason = 'MuJoCo 위치 데이터가 아직 도착하지 않았습니다.';
  } else if ((stateAge as number) > 2.5) {
    navigationUnavailableReason = `MuJoCo 위치 데이터가 오래됐습니다 (${(stateAge as number).toFixed(1)}초).`;
  } else if (!Number.isFinite(hostPosition?.x) || !Number.isFinite(hostPosition?.y) || !Number.isFinite(hostYaw)) {
    navigationUnavailableReason = 'MuJoCo 위치 또는 방향 데이터가 불완전합니다.';
  } else if (!scanStatus) {
    navigationUnavailableReason = '거리 센서 스캔 데이터가 아직 없습니다.';
  } else if (scanStatus.healthy !== true) {
    navigationUnavailableReason = `거리 센서 상태가 비정상입니다${scanStatus.error ? `: ${scanStatus.error}` : scanStatus.status ? ` (${scanStatus.status})` : ''}.`;
  } else if (!Number.isFinite(scanStatus.age_ms) || (scanStatus.age_ms as number) > 1200) {
    navigationUnavailableReason = `거리 센서 데이터가 오래됐습니다${Number.isFinite(scanStatus.age_ms) ? ` (${Math.round(scanStatus.age_ms as number)}ms)` : ''}.`;
  } else if (!Array.isArray(simulationState.obstacle_scan)) {
    navigationUnavailableReason = '거리 센서 측정값 형식이 올바르지 않습니다.';
  }
  const navigationPose = hostStateAvailable
    ? { x: hostPosition!.x!, y: hostPosition!.y!, yaw: hostYaw! }
    : localPose;
  const navigationPoseRef = useRef(navigationPose);
  navigationPoseRef.current = navigationPose;
  const simulationStateRef = useRef(simulationState);
  simulationStateRef.current = simulationState;
  const obstacleScanRef = useRef<RoutePoint[]>([]);
  const lastDynamicReplanRef = useRef(0);
  useEffect(() => {
    obstacleScanRef.current = getDynamicObstaclePoints(simulationState?.obstacle_scan ?? []);
  }, [simulationState]);
  const isMoving = pressedKeys.size > 0 || controlDirection !== null || Math.hypot(joystick.x, joystick.y) >= 0.1;

  useEffect(() => {
    if (!socket || status.socket !== 'connected') return;
    const destinations = [
      ...NAVIGATION_DESTINATIONS,
      ...savedDestinations.map(({ name, x, y }) => ({ name, aliases: [], x, y, kind: 'saved' })),
      ...(homeWaypoint ? [{ name: '집', aliases: ['home'], x: homeWaypoint.x, y: homeWaypoint.y, kind: 'home' }] : []),
    ];
    socket.emit('nomi_destinations_sync', { destinations });
  }, [socket, status.socket, savedDestinations, homeWaypoint]);

  const editDestination = (target: Destination) => {
    setDestination(target);
    setNavigationNotice(null);
    if (navigationStatus === 'navigating') {
      reportNomiNavigationResult('CANCELLED', '목적지가 바뀌어 이전 자동 주행을 취소했습니다.');
      setNavigationStatus('stopped');
      setControlDirection(null);
      clearPlannedRoute('destination_changed');
      sendMoveCommand('stop', 0);
    }
  };

  const beginNavigation = (target: Destination) => {
    logNavigation('begin_requested', { target: { name: target.name, x: target.x, y: target.y } });
    if (!navigationAvailable) {
      setNavigationNotice(navigationUnavailableReason ?? '주행에 필요한 상태를 확인할 수 없습니다.');
      setNavigationStatus('stopped');
      sendMoveCommand('stop', 0);
      reportNomiNavigationResult('FAILED', navigationUnavailableReason ?? '주행에 필요한 상태를 확인할 수 없습니다.');
      return;
    }
    const route = findRoute(navigationPose, target, obstacleScanRef.current);
    if (!route) {
      clearPlannedRoute('planner_no_route', { target: target.name, live_scan_points: obstacleScanRef.current.length });
      setNavigationNotice('장애물과 로봇 여유 공간을 고려해도 통과 가능한 경로를 찾지 못했습니다.');
      setNavigationStatus('blocked');
      sendMoveCommand('stop', 0);
      reportNomiNavigationResult('FAILED', '장애물과 로봇 여유 공간을 고려한 경로를 찾지 못했습니다.');
      return;
    }
    stopContinuousMovement();
    setJoystick({ x: 0, y: 0 });
    setControlDirection(null);
    setDestination(target);
    setPlannedRoute(route);
    setRouteOrigin({ x: navigationPose.x, y: navigationPose.y });
    setWaypointIndex(0);
    turnDirectionRef.current = null;
    motionGuardRef.current.reset();
    lastControllerPhaseRef.current = null;
    setNavigationNotice(null);
    setNavigationStatus('navigating');
    logNavigation('route_planned', { target: target.name, waypoint_count: route.length, route });
  };
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    if (!nomiNavigationRequest) return;
    if (handledNomiRequestRef.current === nomiNavigationRequest.request_id) return;
    handledNomiRequestRef.current = nomiNavigationRequest.request_id;
    activeNomiNavigationRef.current = String(nomiNavigationRequest.request_id);
    const normalizePlaceName = (name: string) => name.normalize('NFKC').replace(/[\s_-]+/g, '').toLocaleLowerCase();
    const requestedName = normalizePlaceName(nomiNavigationRequest.name || nomiNavigationRequest.destination);
    const genericSavedName = ['저장된목적지', '저장된장소', '목적지', 'saved', 'saveddestination'].includes(requestedName);
    const homeRequested = nomiNavigationRequest.destination === 'home' || ['집', 'home'].includes(requestedName);
    const chargingNames = new Set(['충전위치', '충전도크', '충전소', '충전장소', '도킹스테이션', '충전기', 'dock', 'chargingstation']);
    const savedHome = savedDestinations.find(place => normalizePlaceName(place.name) === '집');
    const target = homeRequested
      ? homeWaypoint ?? savedHome
      : genericSavedName
        ? savedDestinations.length === 1 ? savedDestinations[0] : undefined
        : savedDestinations.find(place => normalizePlaceName(place.name) === requestedName
          || (chargingNames.has(requestedName) && chargingNames.has(normalizePlaceName(place.name))));
    if (!target) {
      setNavigationStatus('stopped');
      reportNomiNavigationResult('FAILED', '저장된 목적지를 찾지 못해 주행을 시작하지 않았습니다.');
      setNavigationNotice(genericSavedName
        ? savedDestinations.length === 0
          ? '저장된 목적지가 없습니다. 웹앱에서 목적지 이름과 좌표를 저장한 뒤 다시 요청해 주세요.'
          : '저장된 목적지가 여러 개입니다. 이동할 목적지 이름을 말씀해 주세요.'
        : `저장된 목적지 '${nomiNavigationRequest.name}'을(를) 찾지 못했습니다. 웹앱에서 목적지를 저장한 뒤 다시 요청해 주세요.`);
      return;
    }
    if (!navigationAvailable) {
      setNavigationNotice(`NOMI 목적지 주행을 시작하지 않았습니다. ${navigationUnavailableReason ?? '주행 상태를 확인할 수 없습니다.'}`);
      setNavigationStatus('stopped');
      sendMoveCommand('stop', 0);
      reportNomiNavigationResult('FAILED', navigationUnavailableReason ?? '주행 상태를 확인할 수 없습니다.');
      return;
    }
    if (pressedKeys.size > 0) stopContinuousMovement();
    beginNavigation(target);
  }, [nomiNavigationRequest, homeWaypoint, savedDestinations, hostStateAvailable, navigationAvailable, navigationUnavailableReason, navigationPose, pressedKeys.size, sendMoveCommand, stopContinuousMovement]);

  useEffect(() => {
    if (!nomiNavigationCancel || activeNomiNavigationRef.current !== nomiNavigationCancel.request_id) return;
    reportNomiNavigationResult('CANCELLED', 'NOMI에서 자동 주행 취소를 요청했습니다.');
    setNavigationStatus('stopped');
    setControlDirection(null);
    clearPlannedRoute('nomi_task_cancelled');
    sendMoveCommand('stop', 0);
  }, [nomiNavigationCancel, sendMoveCommand]);

  useEffect(() => {
    if (pressedKeys.size > 0 && plannedRoute.length > 0) {
      reportNomiNavigationResult('CANCELLED', '수동 키 입력으로 자동 주행을 취소했습니다.');
      clearPlannedRoute('manual_keyboard_input');
    }
  }, [pressedKeys.size]);

  useEffect(() => {
    if (navigationStatus !== 'navigating') return;
    if (!navigationAvailable) {
      setControlDirection(null);
      setNavigationNotice(`자동 주행을 중지했습니다. ${navigationUnavailableReason ?? '주행 상태를 확인할 수 없습니다.'}`);
      clearPlannedRoute('navigation_unavailable');
      setNavigationStatus('stopped');
      sendMoveCommand('stop', 0);
      reportNomiNavigationResult('FAILED', navigationUnavailableReason ?? '주행 상태가 유효하지 않습니다.');
      return;
    }
    if (pressedKeys.size > 0) {
      reportNomiNavigationResult('CANCELLED', '수동 조작으로 자동 주행을 취소했습니다.');
      setControlDirection(null);
      clearPlannedRoute('manual_keyboard_cancel');
      setNavigationStatus('stopped');
      return;
    }
    if (speed <= 0) {
      setControlDirection(null);
      setNavigationNotice('주행 속도가 0이라 목적지 주행을 시작하지 않았습니다. 속도를 입력한 뒤 다시 시도해 주세요.');
      clearPlannedRoute('nonpositive_speed');
      setNavigationStatus('stopped');
      sendMoveCommand('stop', 0);
      reportNomiNavigationResult('FAILED', '주행 속도가 0이어서 자동 주행을 시작하지 않았습니다.');
      return;
    }

    let bestDistance = Number.POSITIVE_INFINITY;
    let bestHeadingError = Number.POSITIVE_INFINITY;
    let bestBrakingRate = Number.POSITIVE_INFINITY;
    let lastProgressAt = performance.now();
    logNavigation('route_follower_started', { waypoint_index: waypointIndex, waypoint_count: plannedRoute.length });
    const timer = window.setInterval(() => {
      const pose = navigationPoseRef.current;
      const waypoint = plannedRoute[waypointIndex] ?? destination;
      const dx = waypoint.x - pose.x;
      const dy = waypoint.y - pose.y;
      const distance = Math.hypot(dx, dy);
      const now = performance.now();
      const liveState = simulationStateRef.current;
      const liveScanStatus = liveState?.obstacle_scan_status;
      const liveStateValid = liveState?.host_connected === true
        && Number.isFinite(liveState.state_age) && (liveState.state_age as number) <= 2.5
        && Number.isFinite(liveState.position?.x) && Number.isFinite(liveState.position?.y)
        && Number.isFinite(liveState.rotation?.yaw)
        && liveScanStatus?.healthy === true
        && Number.isFinite(liveScanStatus.age_ms) && (liveScanStatus.age_ms as number) <= 1200
        && Array.isArray(liveState.obstacle_scan);
      if (!liveStateValid) {
        setControlDirection(null);
        setNavigationStatus('stopped');
        setNavigationNotice('MuJoCo 위치 또는 센서 데이터가 오래되었거나 유효하지 않아 자동 주행을 안전 정지했습니다.');
        clearPlannedRoute('live_pose_or_sensor_stale');
        sendMoveCommand('stop', 0);
        reportNomiNavigationResult('FAILED', '최신 위치·방향 또는 센서 상태를 확인하지 못해 안전 정지했습니다.');
        return;
      }
      const desiredYaw = Math.atan2(dy, dx);
      const headingError = Math.abs(Math.atan2(
        Math.sin(desiredYaw - pose.yaw),
        Math.cos(desiredYaw - pose.yaw),
      ));
      const measuredYawRate = simulationStateRef.current?.velocity?.angular?.z ?? 0;
      const actualYawRate = Math.abs(measuredYawRate);
      const liveObstacles = rangeSensorAvailable ? obstacleScanRef.current : [];
      const routeBlocked = isRouteBlockedByDynamicObstacle(pose, plannedRoute, waypointIndex, liveObstacles);
      if (!rangeSensorAvailable) {
        setControlDirection(null);
        setNavigationStatus('stopped');
        setNavigationNotice('MuJoCo 거리 센서 갱신이 중단되어 자동 주행을 안전 정지했습니다.');
        clearPlannedRoute('sensor_unhealthy_or_stale');
        sendMoveCommand('stop', 0);
        reportNomiNavigationResult('FAILED', 'MuJoCo 거리 센서 갱신이 끊겨 안전 정지했습니다.');
        return;
      }
      if (routeBlocked && now - lastDynamicReplanRef.current > 900) {
        lastDynamicReplanRef.current = now;
        const reroute = findRoute(pose, destination, liveObstacles);
        if (!reroute) {
          setControlDirection(null);
          setNavigationStatus('blocked');
          setNavigationNotice('실시간 MuJoCo 거리 센서가 경로의 장애물을 감지해 안전 정지했습니다. 장애물이 사라지면 목적지 주행을 다시 시작해 주세요.');
          clearPlannedRoute('dynamic_obstacle_no_safe_reroute', { dynamic_obstacle_count: liveObstacles.length });
          sendMoveCommand('stop', 0);
          reportNomiNavigationResult('FAILED', '실시간 장애물을 피할 안전한 경로를 찾지 못해 정지했습니다.');
          return;
        }
        setPlannedRoute(reroute);
        logNavigation('dynamic_obstacle_reroute', { old_waypoint_count: plannedRoute.length, new_waypoint_count: reroute.length, dynamic_obstacle_count: liveObstacles.length });
        setRouteOrigin({ x: pose.x, y: pose.y });
        setWaypointIndex(0);
        turnDirectionRef.current = null;
        motionGuardRef.current.reset();
        lastControllerPhaseRef.current = null;
        setNavigationNotice('주행 경로에서 장애물을 감지해 우회 경로를 다시 계산했습니다.');
        setControlDirection(null);
        sendMoveCommand('stop', 0);
        return;
      }
      if (distance < bestDistance - 0.01) {
        bestDistance = Math.min(bestDistance, distance);
        lastProgressAt = now;
      }
      if (headingError < bestHeadingError - 0.01) {
        bestHeadingError = headingError;
        lastProgressAt = now;
      }
      if (headingError <= 0.3 && actualYawRate < bestBrakingRate - 0.02) {
        bestBrakingRate = actualYawRate;
        lastProgressAt = now;
      }
      if (now - lastProgressAt > 15000) {
        setControlDirection(null);
        setNavigationStatus('blocked');
        setNavigationNotice('15초 동안 위치 또는 방향 정렬이 진행되지 않아 정지했습니다. 장애물이나 주행 상태를 확인해 주세요.');
        clearPlannedRoute('navigation_progress_timeout', {
          waypoint_index: waypointIndex,
          distance_m: Number(distance.toFixed(3)),
          heading_error_rad: Number(headingError.toFixed(3)),
          yaw_rate_rad_s: Number(actualYawRate.toFixed(3)),
        });
        sendMoveCommand('stop', 0);
        reportNomiNavigationResult('FAILED', '15초 동안 위치 또는 방향 정렬이 진행되지 않아 자동 주행을 정지했습니다.');
        return;
      }
      const segmentStart = waypointIndex === 0
        ? (routeOrigin ?? pose)
        : plannedRoute[waypointIndex - 1];
      const segmentX = waypoint.x - segmentStart.x;
      const segmentY = waypoint.y - segmentStart.y;
      const segmentLengthSquared = segmentX * segmentX + segmentY * segmentY;
      const segmentLength = Math.sqrt(segmentLengthSquared);
      const alongSegment = segmentLengthSquared > 0
        ? ((pose.x - segmentStart.x) * segmentX + (pose.y - segmentStart.y) * segmentY) / segmentLengthSquared
        : 0;
      const crossTrack = segmentLength > 0
        ? Math.abs(segmentX * (pose.y - segmentStart.y) - segmentY * (pose.x - segmentStart.x)) / segmentLength
        : Number.POSITIVE_INFINITY;
      const isFinalWaypoint = waypointIndex >= plannedRoute.length - 1;
      const passCaptureDistance = isFinalWaypoint ? 0.3 : 0.5;
      const passedWaypoint = alongSegment >= 1
        && distance <= passCaptureDistance
        && crossTrack <= 0.35;
      const waypointPositionReached = distance <= 0.3 || (!isFinalWaypoint && passedWaypoint);
      if (waypointPositionReached && actualYawRate <= 0.05) {
        setControlDirection(null);
        sendMoveCommand('stop', 0);
        if (waypointIndex < plannedRoute.length - 1) {
          turnDirectionRef.current = null;
          motionGuardRef.current.reset();
          lastControllerPhaseRef.current = null;
          setWaypointIndex(index => index + 1);
        } else {
          const actualPose = navigationPoseRef.current;
          const arrivalDistance = Math.hypot(destination.x - actualPose.x, destination.y - actualPose.y);
          if (navigationAvailable && arrivalDistance <= 0.3) {
            setNavigationStatus('arrived');
            reportNomiNavigationResult('SUCCEEDED', `${destination.name || '목적지'}에 도착했습니다.`, actualPose, arrivalDistance);
          } else {
            setNavigationStatus('blocked');
            setNavigationNotice('목적지 도착을 위치 데이터로 확인하지 못해 완료 처리하지 않았습니다.');
            reportNomiNavigationResult('FAILED', '현재 위치가 목적지 0.3m 이내라는 도착 확인이 없습니다.', actualPose, arrivalDistance);
          }
        }
        return;
      }

      const command = computeWaypointCommand(
        pose,
        waypoint,
        speed,
        turnDirectionRef.current,
        measuredYawRate,
      );
      turnDirectionRef.current = command.turnDirection;
      if (command.phase !== lastControllerPhaseRef.current) {
        logNavigation('controller_phase', {
          phase: command.phase,
          waypoint_index: waypointIndex,
          distance_m: Number(command.distance.toFixed(3)),
          desired_yaw_rad: Number(command.desiredYaw.toFixed(3)),
          heading_error_rad: Number(command.headingError.toFixed(3)),
          angular_command_rad_s: Number(command.angular.toFixed(3)),
        });
        lastControllerPhaseRef.current = command.phase;
      }
      const actualVelocity = simulationStateRef.current?.velocity?.linear;
      const actualAngular = simulationStateRef.current?.velocity?.angular?.z ?? 0;
      const motionFault = motionGuardRef.current.observe({
        nowMs: now,
        distance: command.distance,
        commandedX: command.linearX,
        commandedY: command.linearY,
        actualX: actualVelocity?.x ?? 0,
        actualY: actualVelocity?.y ?? 0,
        commandedAngular: command.angular,
        actualAngular,
        damping: command.damping,
      });
      if (motionFault) {
        logNavigation('motion_guard_fault', {
          reason: motionFault,
          phase: command.phase,
          commanded_angular_rad_s: Number(command.angular.toFixed(3)),
          actual_angular_rad_s: Number(actualAngular.toFixed(3)),
          heading_error_rad: Number(command.headingError.toFixed(3)),
        });
        setControlDirection(null);
        setNavigationStatus('blocked');
        setNavigationNotice(motionFault);
        clearPlannedRoute('motion_feedback_mismatch', { reason: motionFault });
        sendMoveCommand('stop', 0);
        reportNomiNavigationResult('FAILED', motionFault);
        return;
      }
      setControlDirection(command.phase === 'aligning' || command.phase === 'braking'
        ? command.angular >= 0 ? 'rotate_left' : 'rotate_right'
        : command.phase === 'driving' ? 'forward' : null);
      sendDriveCommand(command.linearX, command.linearY, command.angular);
    }, 100);
    return () => {
      window.clearInterval(timer);
      logNavigation('route_follower_stopped', { waypoint_index: waypointIndex, waypoint_count: plannedRoute.length });
    };
  }, [destination, hostStateAvailable, navigationAvailable, navigationUnavailableReason, navigationStatus, plannedRoute, pressedKeys.size, rangeSensorAvailable, routeOrigin, sendDriveCommand, sendMoveCommand, speed, waypointIndex]);

  useEffect(() => {
    if (commandFeedback?.direction !== 'drive_vector') return;
    if (navigationStatus !== 'navigating') {
      lastHandledDriveFeedbackSequenceRef.current = Math.max(
        lastHandledDriveFeedbackSequenceRef.current,
        commandFeedback.sequence,
      );
      return;
    }
    if (commandFeedback.status === 'pending'
      || commandFeedback.sequence <= lastHandledDriveFeedbackSequenceRef.current) return;

    lastHandledDriveFeedbackSequenceRef.current = commandFeedback.sequence;
    if (!shouldStopForDriveFeedback(commandFeedback.status)) return;

    const reason = commandFeedback.message || '자동 주행 명령이 서버 안전 검사에서 거부되었습니다.';
    setControlDirection(null);
    setNavigationStatus('blocked');
    setNavigationNotice(`자동 주행 명령을 거부해 정지했습니다. ${reason}`);
    navigationEffectsRef.current.clearPlannedRoute('drive_command_rejected', {
      sequence: commandFeedback.sequence,
      reason,
    });
    sendMoveCommand('stop', 0);
    navigationEffectsRef.current.reportNomiNavigationResult('FAILED', reason);
  }, [commandFeedback, navigationStatus, sendMoveCommand]);

  const handleRotate = (direction: string) => {
    reportNomiNavigationResult('CANCELLED', '수동 회전 명령으로 자동 주행을 취소했습니다.');
    setNavigationStatus('stopped');
    setControlDirection(direction);
    clearPlannedRoute('manual_rotate');
    sendMoveCommand(direction, speed);
  };

  const handleMoveStop = () => {
    reportNomiNavigationResult('CANCELLED', '수동 정지 명령으로 자동 주행을 취소했습니다.');
    setNavigationStatus('stopped');
    setControlDirection(null);
    setJoystick({ x: 0, y: 0 });
    clearPlannedRoute('manual_stop');
    sendMoveCommand('stop', 0);
  };

  const handleJoystickMove = (vector: StickVector) => {
    reportNomiNavigationResult('CANCELLED', '조이스틱 입력으로 자동 주행을 취소했습니다.');
    setNavigationStatus('stopped');
    clearPlannedRoute('joystick_input');
    setJoystick(vector);
    const magnitude = Math.min(1, Math.hypot(vector.x, vector.y));
    if (magnitude < 0.1) {
      setControlDirection(null);
      sendMoveCommand('stop', 0);
      return;
    }

    // Navigation-style steering: turn toward joystick direction, then drive forward.
    // Joystick coordinate: x = right(+)/left(-), y = down(+)/up(-) (screen space)
    // MuJoCo yaw: +X = 0, counter-clockwise positive
    // Joystick up (y<0) = forward = current heading, so desired yaw offset from heading:
    //   joystick angle in screen coords: atan2(-vector.y, vector.x)  (negate y for math coords)
    const joystickAngle = Math.atan2(-vector.y, vector.x);
    // Combine with robot's current heading to get desired world yaw
    const currentYaw = simulationState?.rotation?.yaw ?? localPose.yaw;
    // joystickAngle is relative: up(π/2)=forward, right(0)=right turn, left(π)=left turn
    // Convert to world frame: desired yaw = currentYaw + (joystickAngle - π/2)
    // But for navigation-style, we want: joystick direction = desired world heading
    // joystick up = "keep current heading and drive forward"
    // joystick right = "turn right (decrease yaw) and drive forward"
    const desiredYaw = currentYaw + (joystickAngle - Math.PI / 2);
    const yawError = Math.atan2(
      Math.sin(desiredYaw - currentYaw),
      Math.cos(desiredYaw - currentYaw),
    );

    const absYawError = Math.abs(yawError);
    // Proportional angular steering
    const angularSpeed = Math.max(-0.7, Math.min(0.7, yawError * 1.8));
    // Reduce forward speed when turning sharply (cos-based scaling)
    const alignmentFactor = Math.max(0, Math.cos(yawError));
    const driveSpeed = speed * magnitude * alignmentFactor;

    // Use body-relative forward + angular: drive forward while steering
    const displayDirection = absYawError > 0.3
      ? (yawError > 0 ? 'rotate_left' : 'rotate_right')
      : 'forward';
    setControlDirection(displayDirection);

    const now = performance.now();
    if (now - lastJoystickCommandRef.current >= 60) {
      lastJoystickCommandRef.current = now;
      sendMoveCommand('forward', driveSpeed, angularSpeed);
    }
  };

  const handleEmergencyStop = () => {
    reportNomiNavigationResult('CANCELLED', '긴급 정지로 자동 주행을 취소했습니다.');
    setNavigationStatus('stopped');
    stopContinuousMovement();
    setControlDirection(null);
    clearPlannedRoute('emergency_stop');
    sendMoveCommand('stop', 0);
  };

  const handleReset = () => {
    reportNomiNavigationResult('CANCELLED', '시뮬레이션 초기화로 자동 주행을 취소했습니다.');
    setNavigationStatus('idle');
    setControlDirection(null);
    clearPlannedRoute('simulation_reset');
    setNavigationNotice(null);
    setLocalPose({ x: 0, y: 0, yaw: 0 });
    setResetToken(token => token + 1);
    socket?.emit('reset_robot');
  };

  const startNavigation = () => {
    if (!destination.name.trim() || !Number.isFinite(destination.x) || !Number.isFinite(destination.y)
      || destination.x < INDOOR_MAP.bounds.minX || destination.x > INDOOR_MAP.bounds.maxX
      || destination.y < INDOOR_MAP.bounds.minY || destination.y > INDOOR_MAP.bounds.maxY) return;
    beginNavigation(destination);
  };

  const stopNavigation = () => {
    reportNomiNavigationResult('CANCELLED', '사용자가 목적지 주행을 취소했습니다.');
    setNavigationStatus('stopped');
    setControlDirection(null);
    clearPlannedRoute('navigation_stopped_by_user');
    sendMoveCommand('stop', 0);
  };

  const persistDestination = (place: Destination) => {
    if (!place.name || !Number.isFinite(place.x) || !Number.isFinite(place.y)
      || place.x < INDOOR_MAP.bounds.minX || place.x > INDOOR_MAP.bounds.maxX
      || place.y < INDOOR_MAP.bounds.minY || place.y > INDOOR_MAP.bounds.maxY) return;
    const updated = [...savedDestinations.filter(item => item.name !== place.name), place].slice(-30);
    setSavedDestinations(updated);
    try {
      localStorage.setItem('xlerobot.savedDestinations', JSON.stringify(updated));
    } catch {
      // The current session still keeps saved places if browser storage is blocked.
    }
    if (place.name.normalize('NFKC').trim() === '집') {
      setHomeWaypoint(place);
      try {
        localStorage.setItem('xlerobot.homeWaypoint', JSON.stringify(place));
      } catch {
        // The current session still uses this home waypoint.
      }
    }
  };

  const saveDestination = () => {
    persistDestination({ name: destination.name.trim(), x: destination.x, y: destination.y });
  };

  const currentPosition = hostPositionFresh
    ? { x: hostPosition!.x!, y: hostPosition!.y! }
    : null;
  const currentPositionUnavailableReason = status.socket !== 'connected'
    ? '현재 위치를 저장할 수 없습니다. 웹 서버 연결이 없습니다.'
    : simulationState?.host_connected !== true
      ? '현재 위치를 저장할 수 없습니다. MuJoCo 위치 데이터가 없습니다.'
      : !Number.isFinite(stateAge)
        ? '현재 위치를 저장할 수 없습니다. 위치 데이터 대기 중입니다.'
        : (stateAge as number) > 2.5
          ? `현재 위치를 저장할 수 없습니다. 위치 데이터가 오래됐습니다 (${(stateAge as number).toFixed(1)}초).`
          : '현재 위치 좌표가 올바르지 않습니다.';
  const saveCurrentPosition = () => {
    if (!currentPosition || !destination.name.trim()) return;
    const place = { name: destination.name.trim(), x: currentPosition.x, y: currentPosition.y };
    setDestination(place);
    persistDestination(place);
  };

  const destinationNavigator = <DestinationNavigator
    destination={destination}
    homeWaypoint={homeWaypoint}
    savedDestinations={savedDestinations}
    plannedRoute={plannedRoute}
    navigationNotice={navigationNotice}
    currentPose={navigationPose}
    currentPosition={currentPosition}
    currentPositionUnavailableReason={currentPositionUnavailableReason}
    navigationAvailable={navigationAvailable}
    navigationUnavailableReason={navigationUnavailableReason}
    status={navigationStatus}
    onDestinationChange={editDestination}
    onSelectDestination={editDestination}
    onStart={startNavigation}
    onStop={stopNavigation}
    onSaveDestination={saveDestination}
    onSaveCurrentPosition={saveCurrentPosition}
  />;

  const socketConnected = status.socket === 'connected';
  const hostConnected = hostStateAvailable;

  return (
    <main className="app-shell min-h-[100svh] selection:bg-blue-200">
      <div className="mx-auto max-w-[1720px] px-3 pb-[calc(5.25rem+env(safe-area-inset-bottom))] pt-3 sm:px-6 sm:pb-8 sm:pt-4 lg:px-8">
        <header className="app-header mb-3 flex flex-wrap items-center justify-between gap-3 border-b pb-3 sm:mb-5 sm:gap-4 sm:pb-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600"><Bot size={22} /></div>
            <div>
              <div className="text-[10px] font-bold tracking-[0.18em] text-blue-600">NOMI × XLEROBOT</div>
              <h1 className="text-base font-bold tracking-tight text-[var(--ui-fg)] sm:text-xl">SIM ARENA <span className="ml-1 hidden font-medium text-[var(--ui-muted)] sm:inline">/ PILOT CONSOLE</span></h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="status-pill flex items-center gap-2 rounded-xl border px-3 py-2 text-xs">
              <span className={`h-2 w-2 rounded-full ${socketConnected ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className="text-[var(--ui-muted)] sm:hidden">{socketConnected ? (hostConnected ? 'HOST LIVE' : 'SERVER') : 'LOCAL'}</span>
              <span className="hidden text-[var(--ui-muted)] sm:inline">{socketConnected ? (hostConnected ? 'SERVER + MUJOCO LIVE' : 'SERVER CONNECTED · HOST WAITING') : 'LOCAL SIMULATION'}</span>
            </div>
            {commandFeedback && <div className="status-pill hidden rounded-xl border px-3 py-2 text-[10px] text-[var(--ui-muted)] md:block" title={commandFeedback.message ?? ''}>
              CMD #{commandFeedback.sequence} · {commandFeedback.status.toUpperCase()}{commandFeedback.latencyMs !== null ? ` · ${commandFeedback.latencyMs} ms` : ''}
            </div>}
            <button onClick={sendPing} title="Ping simulation server" className="toolbar-button rounded-xl border p-2.5 transition"><Radio size={16} /></button>
            <button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} title="Toggle theme" className="toolbar-button rounded-xl border p-2.5 transition">
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        <div className="mobile-dashboard-grid grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1.85fr)_minmax(360px,0.9fr)]">
          <section className="min-w-0">
            <div className="mb-2 flex items-end justify-between gap-3 sm:mb-3">
              <div>
                <div className="text-[10px] font-semibold tracking-[0.12em] text-[var(--ui-muted)]">시뮬레이션 · 자유 주행</div>
                <h2 className="mt-1 text-sm font-semibold text-[var(--ui-fg)]">XLeRobot 시뮬레이션 구역</h2>
              </div>
              <div className="hidden items-center gap-2 text-[10px] font-medium tracking-wide text-[var(--ui-muted)] sm:flex"><Cpu size={13} className="text-blue-600" /> SIMULATION VIEW</div>
            </div>
            <GameSimulationCanvas
              simulationState={hostConnected ? simulationState : null}
              pressedKeys={pressedKeys}
              controlDirection={controlDirection}
              joystick={joystick}
              speed={speed}
              connected={socketConnected}
              resetToken={resetToken}
              onReset={handleReset}
              onPoseUpdate={setLocalPose}
              destination={destination}
              savedDestinations={savedDestinations}
              plannedRoute={plannedRoute}
            />
            <div className="mt-3 hidden xl:block xl:mt-4">
              <GameControlDeck
                speed={speed}
                onSpeedChange={setSpeed}
                onJoystickMove={handleJoystickMove}
                onRotate={handleRotate}
                onMoveStop={handleMoveStop}
                onEmergencyStop={handleEmergencyStop}
                onReset={handleReset}
                connected={hostConnected}
              />
              <div className="mt-3">{destinationNavigator}</div>
            </div>
          </section>

          <aside className="hidden space-y-4 xl:block">
            <RobotTelemetry
              state={hostConnected ? simulationState : null}
              localPose={localPose}
              speed={speed}
              moving={isMoving}
              socketStatus={status.socket}
            />
            <NomiPanel socket={socket} theme={theme} />
          </aside>
        </div>

        <section className="mobile-control-panel mt-3 xl:hidden" aria-label="Mobile control panel">
          {mobilePanel === 'drive' && (
            <>
              <GameControlDeck
                speed={speed}
                onSpeedChange={setSpeed}
                onJoystickMove={handleJoystickMove}
                onRotate={handleRotate}
                onMoveStop={handleMoveStop}
                onEmergencyStop={handleEmergencyStop}
                onReset={handleReset}
                connected={hostConnected}
              />
              <div className="mt-3">{destinationNavigator}</div>
            </>
          )}
          {mobilePanel === 'nomi' && <NomiPanel socket={socket} theme={theme} />}
          {mobilePanel === 'status' && (
            <RobotTelemetry state={hostConnected ? simulationState : null} localPose={localPose} speed={speed} moving={isMoving} socketStatus={status.socket} />
          )}
        </section>

        <footer className="mt-5 hidden flex-wrap items-center justify-between gap-2 border-t border-[var(--ui-card-border)] pt-3 text-[10px] font-medium tracking-wide text-[var(--ui-muted)] xl:flex">
          <span>W A S D / ARROWS · MOVE</span>
          <span>Q / E · 회전</span>
          <span>시뮬레이션 데이터 · 카메라 미사용</span>
        </footer>
      </div>
      <nav className="mobile-nav fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t px-2 pt-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] backdrop-blur-xl xl:hidden" aria-label="Mobile navigation">
        {([
          ['drive', Gamepad2, '조종'],
          ['nomi', MessageCircle, 'NOMI'],
          ['status', SlidersHorizontal, '상태'],
        ] as const).map(([panel, Icon, label]) => (
          <button key={panel} onClick={() => setMobilePanel(panel)} aria-current={mobilePanel === panel ? 'page' : undefined} className={`mobile-nav-button flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-semibold transition ${mobilePanel === panel ? 'is-active' : ''}`}>
            <Icon size={19} strokeWidth={2.2} />{label}
          </button>
        ))}
      </nav>
    </main>
  );
}
