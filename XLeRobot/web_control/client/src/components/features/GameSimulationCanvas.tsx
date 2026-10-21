import { useEffect, useRef, useState } from 'react';
import { Crosshair, MapPin, RotateCcw, Wifi, WifiOff } from 'lucide-react';
import type { RobotSimulationState } from '../../types';
import { STATIC_OBSTACLES, type RoutePoint } from '../../utils/pathPlanner';
import { INDOOR_MAP } from '../../utils/indoorMap';

interface Pose {
  x: number;
  y: number;
  yaw: number;
}

interface GameSimulationCanvasProps {
  simulationState: RobotSimulationState | null;
  pressedKeys: Set<string>;
  controlDirection: string | null;
  joystick: { x: number; y: number };
  speed: number;
  connected: boolean;
  resetToken: number;
  destination: { name: string; x: number; y: number } | null;
  savedDestinations: Array<{ name: string; x: number; y: number }>;
  plannedRoute: RoutePoint[];
  onReset: () => void;
  onPoseUpdate: (pose: Pose) => void;
}

const MOVEMENT_KEYS: Record<string, string> = {
  w: 'forward', W: 'forward', ArrowUp: 'forward',
  s: 'backward', S: 'backward', ArrowDown: 'backward',
  a: 'left', A: 'left', ArrowLeft: 'left',
  d: 'right', D: 'right', ArrowRight: 'right',
  q: 'rotate_left', Q: 'rotate_left',
  e: 'rotate_right', E: 'rotate_right',
};

function drawIndoorMap(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  pose: Pose,
  destination: { name: string; x: number; y: number } | null,
  route: RoutePoint[],
  scan: RoutePoint[],
  savedDestinations: Array<{ name: string; x: number; y: number }>,
) {
  const { minX, maxX, minY, maxY } = INDOOR_MAP.bounds;
  const margin = 24;
  const header = 48;
  const footer = 52;
  const scale = Math.max(1, Math.min((width - margin * 2) / (maxX - minX), (height - header - footer) / (maxY - minY)));
  const roomWidth = (maxX - minX) * scale;
  const roomHeight = (maxY - minY) * scale;
  const left = (width - roomWidth) / 2;
  const top = header + (height - header - footer - roomHeight) / 2;
  const point = (x: number, y: number) => ({ x: left + (x - minX) * scale, y: top + (maxY - y) * scale });

  ctx.fillStyle = '#eaf0f5';
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(left, top, roomWidth, roomHeight);
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, roomWidth, roomHeight);
  ctx.clip();
  ctx.strokeStyle = 'rgba(100, 116, 139, 0.12)';
  ctx.lineWidth = 1;
  for (let x = Math.ceil(minX); x <= maxX; x += 1) {
    const a = point(x, minY); const b = point(x, maxY);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  for (let y = Math.ceil(minY); y <= maxY; y += 1) {
    const a = point(minX, y); const b = point(maxX, y);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  ctx.restore();

  // Four wall runs leave only the centered south entrance open.
  ctx.fillStyle = '#475569';
  const wall = Math.max(5, scale * 0.16);
  ctx.fillRect(left - wall, top - wall, roomWidth + wall * 2, wall);
  ctx.fillRect(left - wall, top + roomHeight, roomWidth + wall * 2, wall);
  ctx.fillRect(left - wall, top, wall, roomHeight);
  ctx.fillRect(left + roomWidth, top, wall, roomHeight);
  ctx.fillStyle = '#0f766e';
  ctx.fillRect(left + roomWidth / 2 - INDOOR_MAP.doorway.width * scale / 2, top + roomHeight - wall / 2,
    INDOOR_MAP.doorway.width * scale, wall);
  ctx.fillStyle = '#f0fdfa';
  ctx.font = 'bold 9px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('출입구', left + roomWidth / 2, top + roomHeight + wall + 10);

  for (const table of STATIC_OBSTACLES) {
    const center = point(table.x, table.y);
    const w = table.halfWidth * 2 * scale;
    const h = table.halfHeight * 2 * scale;
    ctx.fillStyle = 'rgba(15, 23, 42, 0.14)';
    ctx.fillRect(center.x - w / 2 + 2, center.y - h / 2 + 3, w, h);
    ctx.fillStyle = '#b77945';
    ctx.strokeStyle = '#7c4a2d';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.roundRect(center.x - w / 2, center.y - h / 2, w, h, 5); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#fff7ed';
    ctx.font = 'bold 9px sans-serif';
    ctx.fillText(table.name, center.x, center.y + 3);
  }

  // Fresh range returns are in the same map frame and appear as orange detections.
  ctx.fillStyle = 'rgba(249, 115, 22, 0.72)';
  for (const obstacle of scan) {
    if (obstacle.x < minX || obstacle.x > maxX || obstacle.y < minY || obstacle.y > maxY) continue;
    const p = point(obstacle.x, obstacle.y);
    ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(1.5, scale * 0.035), 0, Math.PI * 2); ctx.fill();
  }

  if (route.length > 0) {
    ctx.strokeStyle = '#0891b2';
    ctx.lineWidth = Math.max(2, scale * 0.055);
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    const start = point(pose.x, pose.y); ctx.moveTo(start.x, start.y);
    for (const waypoint of route) { const p = point(waypoint.x, waypoint.y); ctx.lineTo(p.x, p.y); }
    ctx.stroke(); ctx.setLineDash([]);
  }
  for (const saved of savedDestinations) {
    if (!Number.isFinite(saved.x) || !Number.isFinite(saved.y)
      || saved.x < minX || saved.x > maxX || saved.y < minY || saved.y > maxY) continue;
    const marker = point(saved.x, saved.y);
    ctx.fillStyle = '#2563eb';
    ctx.beginPath(); ctx.arc(marker.x, marker.y, Math.max(3, scale * 0.07), 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#1d4ed8'; ctx.font = 'bold 8px sans-serif'; ctx.fillText(saved.name, marker.x, marker.y - 7);
  }
  if (destination && Number.isFinite(destination.x) && Number.isFinite(destination.y)) {
    const target = point(destination.x, destination.y);
    ctx.strokeStyle = '#16a34a'; ctx.fillStyle = 'rgba(34, 197, 94, 0.18)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(target.x, target.y, Math.max(7, scale * 0.22), 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#166534'; ctx.font = 'bold 9px sans-serif'; ctx.fillText(destination.name, target.x, target.y - 10);
  }

  const start = point(INDOOR_MAP.start.x, INDOOR_MAP.start.y);
  ctx.fillStyle = '#64748b'; ctx.beginPath(); ctx.arc(start.x, start.y, Math.max(3, scale * 0.07), 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#475569'; ctx.font = '8px sans-serif'; ctx.fillText('시작', start.x + 13, start.y - 7);
  const charger = point(INDOOR_MAP.charging.x, INDOOR_MAP.charging.y);
  ctx.fillStyle = '#059669'; ctx.beginPath(); ctx.arc(charger.x, charger.y, Math.max(4, scale * 0.1), 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#047857'; ctx.font = 'bold 8px sans-serif'; ctx.fillText('충전 위치', charger.x, charger.y - 9);

  const robot = point(pose.x, pose.y);
  ctx.save();
  ctx.translate(robot.x, robot.y);
  ctx.rotate(-pose.yaw);
  ctx.fillStyle = '#0e7490'; ctx.strokeStyle = '#ecfeff'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(scale * 0.22, 0); ctx.lineTo(-scale * 0.14, -scale * 0.14);
  ctx.lineTo(-scale * 0.10, 0); ctx.lineTo(-scale * 0.14, scale * 0.14); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.restore();
}

export function GameSimulationCanvas({
  simulationState,
  pressedKeys,
  controlDirection,
  joystick,
  speed,
  connected,
  resetToken,
  destination,
  savedDestinations,
  plannedRoute,
  onReset,
  onPoseUpdate,
}: GameSimulationCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const poseRef = useRef<Pose>({ x: 0, y: 0, yaw: 0 });
  const remotePoseRef = useRef<Pose | null>(null);
  const lastRemotePoseRef = useRef<Pose | null>(null);
  const remoteOffsetRef = useRef<Pose>({ x: 0, y: 0, yaw: 0 });
  const drivingRef = useRef(false);
  const inputsRef = useRef({ keys: pressedKeys, direction: controlDirection, joystick, speed, simulationState, destination, savedDestinations, plannedRoute });
  const fpsRef = useRef({ last: 0, value: 0 });
  const lastUiUpdateRef = useRef(0);
  const poseCallbackRef = useRef(onPoseUpdate);
  const [displayPose, setDisplayPose] = useState<Pose>({ x: 0, y: 0, yaw: 0 });
  const [fps, setFps] = useState(0);

  useEffect(() => {
    inputsRef.current = { keys: pressedKeys, direction: controlDirection, joystick, speed, simulationState, destination, savedDestinations, plannedRoute };
  }, [pressedKeys, controlDirection, joystick, speed, simulationState, destination, savedDestinations, plannedRoute]);

  useEffect(() => {
    poseCallbackRef.current = onPoseUpdate;
  }, [onPoseUpdate]);

  useEffect(() => {
    const isDriving = pressedKeys.size > 0 || controlDirection !== null || Math.hypot(joystick.x, joystick.y) >= 0.1;
    if (isDriving) {
      drivingRef.current = true;
      remotePoseRef.current = null;
      return;
    }

    if (drivingRef.current) {
      const lastRemote = lastRemotePoseRef.current;
      if (lastRemote) {
        // Keep the game-view pose where local steering left it, then follow only
        // new MuJoCo movement from that point. This prevents snapping back to an
        // older host coordinate when the held key is released.
        remoteOffsetRef.current = {
          x: poseRef.current.x - lastRemote.x,
          y: poseRef.current.y - lastRemote.y,
          yaw: poseRef.current.yaw - lastRemote.yaw,
        };
      }
      drivingRef.current = false;
    }

    const lastRemote = lastRemotePoseRef.current;
    if (lastRemote) {
      remotePoseRef.current = {
        x: lastRemote.x + remoteOffsetRef.current.x,
        y: lastRemote.y + remoteOffsetRef.current.y,
        yaw: lastRemote.yaw + remoteOffsetRef.current.yaw,
      };
    }
  }, [pressedKeys, controlDirection, joystick]);

  useEffect(() => {
    const position = simulationState?.position;
    const yaw = simulationState?.rotation?.yaw;
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      lastRemotePoseRef.current = {
        x: position.x ?? poseRef.current.x,
        y: position.y ?? poseRef.current.y,
        yaw: Number.isFinite(yaw) ? (yaw as number) : poseRef.current.yaw,
      };
      if (!drivingRef.current) {
        remotePoseRef.current = {
          x: lastRemotePoseRef.current.x + remoteOffsetRef.current.x,
          y: lastRemotePoseRef.current.y + remoteOffsetRef.current.y,
          yaw: lastRemotePoseRef.current.yaw + remoteOffsetRef.current.yaw,
        };
      }
    }
  }, [simulationState]);

  useEffect(() => {
    poseRef.current = { x: 0, y: 0, yaw: 0 };
    remotePoseRef.current = { x: 0, y: 0, yaw: 0 };
    lastRemotePoseRef.current = null;
    remoteOffsetRef.current = { x: 0, y: 0, yaw: 0 };
    drivingRef.current = false;
  }, [resetToken]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    let animationFrame = 0;
    let previousTime = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    const draw = (time: number) => {
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      const delta = previousTime ? Math.min((time - previousTime) / 1000, 0.05) : 0;
      previousTime = time;
      const input = inputsRef.current;
      const directions = new Set<string>();
      input.keys.forEach(key => {
        const direction = MOVEMENT_KEYS[key];
        if (direction) directions.add(direction);
      });
      if (input.direction) directions.add(input.direction);
      const keyForward = (directions.has('forward') ? 1 : 0) - (directions.has('backward') ? 1 : 0);
      const keyStrafe = (directions.has('right') ? 1 : 0) - (directions.has('left') ? 1 : 0);
      const stickMagnitude = Math.hypot(input.joystick.x, input.joystick.y);
      const forward = stickMagnitude >= 0.1 ? -input.joystick.y / stickMagnitude : keyForward;
      const strafe = stickMagnitude >= 0.1 ? input.joystick.x / stickMagnitude : keyStrafe;
      const turn = (directions.has('rotate_left') ? 1 : 0) - (directions.has('rotate_right') ? 1 : 0);
      const current = poseRef.current;
      const isDriving = directions.size > 0 || stickMagnitude >= 0.1;
      const remotePose = remotePoseRef.current;
      const livePosition = input.simulationState?.position;
      const liveYaw = input.simulationState?.rotation?.yaw;
      const hasLivePose = livePosition
        && Number.isFinite(livePosition.x)
        && Number.isFinite(livePosition.y)
        && Number.isFinite(liveYaw);
      if (hasLivePose) {
        // MuJoCo is authoritative while connected. Do not animate a second,
        // approximate pose from controlDirection while the real host is moving.
        current.x = livePosition.x as number;
        current.y = livePosition.y as number;
        current.yaw = liveYaw as number;
        remotePoseRef.current = null;
        drivingRef.current = false;
      } else {
        if (isDriving) {
          remotePoseRef.current = null;
        } else if (remotePose) {
          const blend = 1 - Math.exp(-8 * delta);
          current.x += (remotePose.x - current.x) * blend;
          current.y += (remotePose.y - current.y) * blend;
          const yawDifference = Math.atan2(Math.sin(remotePose.yaw - current.yaw), Math.cos(remotePose.yaw - current.yaw));
          current.yaw += yawDifference * blend;
          if (Math.abs(remotePose.x - current.x) + Math.abs(remotePose.y - current.y) + Math.abs(yawDifference) < 0.005) {
            current.x = remotePose.x;
            current.y = remotePose.y;
            current.yaw = remotePose.yaw;
            remotePoseRef.current = null;
          }
        }
        const speedUnits = 1.25 * input.speed;
        // Match the MuJoCo chassis frame: +yaw turns left and slide axes remain fixed.
        const yawCosine = Math.cos(current.yaw);
        const yawSine = Math.sin(current.yaw);
        current.x += (forward * yawCosine + strafe * yawSine) * speedUnits * delta;
        current.y += (forward * yawSine - strafe * yawCosine) * speedUnits * delta;
        current.yaw += turn * 1.4 * delta;
      }

      ctx.clearRect(0, 0, width, height);
      const status = input.simulationState?.obstacle_scan_status;
      const scan = status?.healthy && Number.isFinite(status.age_ms) && (status.age_ms as number) <= 350
        ? input.simulationState?.obstacle_scan ?? []
        : [];
      drawIndoorMap(ctx, width, height, current, input.destination, input.plannedRoute,
        scan.map(({ x, y }) => ({ x, y })), input.savedDestinations);
      fpsRef.current.value = previousTime ? Math.round(1000 / Math.max(1, time - fpsRef.current.last)) : 0;
      fpsRef.current.last = time;
      if (time - lastUiUpdateRef.current > 200) {
        lastUiUpdateRef.current = time;
        setDisplayPose({ ...current });
        setFps(fpsRef.current.value);
        poseCallbackRef.current({ ...current });
      }
      animationFrame = window.requestAnimationFrame(draw);
    };

    animationFrame = window.requestAnimationFrame(draw);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
    };
  }, []);

  const pose = displayPose;
  const sourceLabel = simulationState ? 'MUJOCO SYNC' : connected ? 'SIM SERVER' : 'LOCAL SIM';
  const sourceColor = simulationState ? 'text-emerald-300' : connected ? 'text-sky-300' : 'text-amber-300';
  const scanStatus = simulationState?.obstacle_scan_status;
  const scanFresh = scanStatus?.healthy === true
    && Number.isFinite(scanStatus.age_ms) && (scanStatus.age_ms as number) <= 350;

  return (
    <div className="game-simulation-viewport relative h-[min(43svh,400px)] min-h-[250px] overflow-hidden rounded-2xl border border-slate-600/70 bg-slate-950 shadow-[0_24px_70px_-34px_rgba(0,0,0,0.9)] sm:h-[420px] sm:min-h-[420px] lg:h-[calc(100vh-250px)] lg:max-h-[760px]">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-label="XLeRobot game-style simulation viewport" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(3,9,16,0.55),transparent_24%,transparent_69%,rgba(3,9,16,0.55))]" />

      <div className="absolute left-4 top-4 flex flex-wrap items-center gap-2 sm:left-6 sm:top-6">
        <div className="rounded-lg border border-cyan-200/20 bg-slate-950/75 px-3 py-2 backdrop-blur-md">
          <div className="text-[10px] font-bold tracking-[0.24em] text-cyan-200/70">XLR // INDOOR MAP</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-semibold text-white">
            <span className={`h-2 w-2 rounded-full ${simulationState ? 'bg-emerald-400' : connected ? 'bg-sky-400' : 'bg-amber-400'} shadow-[0_0_12px_currentColor]`} />
            {sourceLabel}
          </div>
        </div>
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-3 py-2 text-xs text-slate-200 backdrop-blur-md">
          <span className="text-slate-500">ZONE</span> <span className="ml-1 font-mono">CLASSROOM 01</span>
        </div>
        {simulationState && (
          <div title={`${scanStatus?.beam_count ?? 0} beams × ${scanStatus?.layer_heights_m?.length ?? 0} heights · ${scanStatus?.range_m ?? 0} m max · ${scanStatus?.scan_duration_ms ?? 0} ms scan · ${scanStatus?.error ?? ''}`} className={`rounded-lg border px-3 py-2 text-xs backdrop-blur-md ${scanFresh ? 'border-emerald-300/20 bg-slate-950/70 text-emerald-100' : 'border-amber-300/20 bg-slate-950/70 text-amber-100'}`}>
            <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${scanFresh ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            {scanFresh
          ? `RANGE ${scanStatus?.hit_count ?? simulationState.obstacle_scan?.length ?? 0} · ${scanStatus?.range_m ?? 0}m · ${scanStatus?.age_ms ?? 0}ms old`
              : `RANGE ${scanStatus?.status?.toUpperCase() ?? 'STALE'}`}
          </div>
        )}
      </div>

      <div className="absolute right-4 top-4 flex items-start gap-2 sm:right-6 sm:top-6">
        <div className="rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2 text-right backdrop-blur-md">
          <div className={`flex items-center justify-end gap-1.5 text-[10px] font-bold tracking-[0.18em] ${sourceColor}`}>
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}{sourceLabel}
          </div>
          <div className="mt-1 font-mono text-[11px] text-slate-300">{pose.x.toFixed(2)}, {pose.y.toFixed(2)} m</div>
          <div className="mt-0.5 font-mono text-[9px] text-slate-500">{fps} FPS · SIM VIEW</div>
        </div>
        <button onClick={onReset} title="Reset simulation" className="pointer-events-auto rounded-lg border border-white/10 bg-slate-950/75 p-2.5 text-slate-200 transition hover:border-cyan-300/60 hover:text-cyan-200">
          <RotateCcw size={16} />
        </button>
      </div>

      <div className="absolute bottom-4 left-4 right-4 flex items-end justify-between gap-3 sm:bottom-6 sm:left-6 sm:right-6">
        <div className="rounded-lg border border-white/10 bg-slate-950/75 px-3 py-2 backdrop-blur-md">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-[0.2em] text-emerald-300"><MapPin size={12} /> FREE ROAM</div>
          <div className="mt-1 font-mono text-xs text-slate-300">HEADING {((pose.yaw * 180 / Math.PI + 360) % 360).toFixed(0)}°</div>
        </div>
        <div className="hidden items-center gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2 text-[10px] font-mono text-slate-300 backdrop-blur-md sm:flex">
          <Crosshair size={13} className="text-cyan-300" /> WASD MOVE <span className="text-slate-600">/</span> Q E TURN
        </div>
        <div className="rounded-lg border border-cyan-200/15 bg-slate-950/75 px-3 py-2 text-right backdrop-blur-md">
          <div className="text-[10px] font-bold tracking-[0.2em] text-slate-500">DRIVE</div>
          <div className="mt-1 font-mono text-sm font-bold text-cyan-200">{speed.toFixed(2)}×</div>
        </div>
      </div>
    </div>
  );
}
