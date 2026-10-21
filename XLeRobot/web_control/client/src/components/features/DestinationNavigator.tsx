import { Home, MapPin, Navigation, Square } from 'lucide-react';
import type { RoutePoint } from '../../utils/pathPlanner';
import { CHARGING_DESTINATION, TABLE_APPROACH_DESTINATIONS } from '../../utils/indoorMap';

export interface Destination {
  name: string;
  x: number;
  y: number;
}

interface DestinationNavigatorProps {
  destination: Destination;
  homeWaypoint: Destination | null;
  savedDestinations: Destination[];
  plannedRoute: RoutePoint[];
  navigationNotice: string | null;
  currentPose: { x: number; y: number; yaw: number };
  currentPosition: { x: number; y: number } | null;
  currentPositionUnavailableReason: string | null;
  navigationAvailable: boolean;
  navigationUnavailableReason: string | null;
  status: 'idle' | 'navigating' | 'arrived' | 'stopped' | 'blocked';
  onDestinationChange: (destination: Destination) => void;
  onSelectDestination: (destination: Destination) => void;
  onStart: () => void;
  onStop: () => void;
  onSaveDestination: () => void;
  onSaveCurrentPosition: () => void;
}

export function DestinationNavigator({ destination, homeWaypoint, savedDestinations, plannedRoute, navigationNotice, currentPose, currentPosition, currentPositionUnavailableReason, navigationAvailable, navigationUnavailableReason, status, onDestinationChange, onSelectDestination, onStart, onStop, onSaveDestination, onSaveCurrentPosition }: DestinationNavigatorProps) {
  const setPreset = (name: string, x: number, y: number) => onDestinationChange({ name, x, y });
  const destinationNameValid = destination.name.trim().length > 0;
  const destinationCoordinatesValid = Number.isFinite(destination.x) && Number.isFinite(destination.y)
    && destination.x >= -5 && destination.x <= 5 && destination.y >= -4 && destination.y <= 8;
  const movementUnavailableReason = !navigationAvailable
    ? navigationUnavailableReason ?? 'MuJoCo 주행 상태와 센서 데이터를 확인할 수 없습니다.'
    : !destinationNameValid
      ? '목적지를 선택하거나 이름을 입력하세요.'
      : !destinationCoordinatesValid
        ? '목적지 좌표가 비어 있거나 허용된 지도 범위를 벗어났습니다.'
        : null;

  return (
    <section className="surface-card rounded-2xl border p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-[0.2em] text-slate-500"><Navigation size={13} /> 목적지 주행</div>
          <div className="mt-1 text-sm font-semibold text-[var(--ui-fg)]">위치를 지정하면 자동으로 이동합니다</div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${status === 'navigating' ? 'bg-blue-100 text-blue-700' : status === 'arrived' ? 'bg-emerald-100 text-emerald-700' : status === 'blocked' ? 'bg-rose-100 text-rose-700' : 'bg-slate-100 text-slate-600'}`}>
          {status === 'navigating' ? '이동 중' : status === 'arrived' ? '도착' : status === 'blocked' ? '진전 없음 · 정지' : status === 'stopped' ? '정지됨' : '대기'}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={!homeWaypoint} onClick={() => homeWaypoint && setPreset(homeWaypoint.name, homeWaypoint.x, homeWaypoint.y)} title={!homeWaypoint ? '목적지 이름을 집으로 저장하면 등록됩니다.' : undefined} className="secondary-button flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"><Home size={14} /> 집</button>
        {TABLE_APPROACH_DESTINATIONS.map(place => <button key={place.name} type="button" onClick={() => setPreset(place.name, place.x, place.y)} className="secondary-button flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold">{place.name}</button>)}
        <button type="button" onClick={() => setPreset(CHARGING_DESTINATION.name, CHARGING_DESTINATION.x, CHARGING_DESTINATION.y)} className="secondary-button flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold"><MapPin size={14} /> 충전 위치</button>
        {savedDestinations.find(place => ['충전위치', '충전도크', '충전소', '충전장소', '도킹스테이션', '충전기', 'dock', 'chargingstation'].includes(place.name.replace(/[\s_-]+/g, '').toLowerCase())) && (() => {
          const charging = savedDestinations.find(place => ['충전위치', '충전도크', '충전소', '충전장소', '도킹스테이션', '충전기', 'dock', 'chargingstation'].includes(place.name.replace(/[\s_-]+/g, '').toLowerCase()))!;
          return <button type="button" onClick={() => setPreset(charging.name, charging.x, charging.y)} className="secondary-button flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold"><MapPin size={14} /> 충전 도크</button>;
        })()}
      </div>

      {savedDestinations.length > 0 && <div className="mt-3">
        <div className="mb-1.5 text-[9px] font-bold tracking-widest text-slate-500">저장된 장소</div>
        <div className="flex flex-wrap gap-2">
          {savedDestinations.map(place => <button key={place.name} type="button" onClick={() => onSelectDestination(place)} className={`secondary-button rounded-lg border px-3 py-1.5 text-xs ${destination.name === place.name ? 'border-blue-300 bg-blue-50 text-blue-700' : ''}`}>{place.name} <span className="ml-1 font-mono opacity-60">{place.x.toFixed(2)}, {place.y.toFixed(2)}</span></button>)}
        </div>
      </div>}

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1fr)_100px_100px_auto_auto] sm:items-end">
        <label className="col-span-2 text-[10px] font-semibold text-slate-500 sm:col-span-1">목적지 이름
          <input value={destination.name} onChange={event => onDestinationChange({ ...destination, name: event.target.value })} className="speed-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" placeholder="예: 집" />
        </label>
        <label className="text-[10px] font-semibold text-slate-500">X 좌표
          <input type="number" min="-5" max="5" step="0.01" value={Number.isFinite(destination.x) ? destination.x : ''} onChange={event => onDestinationChange({ ...destination, x: event.target.value === '' ? Number.NaN : Number(event.target.value) })} className="speed-input mt-1 w-full rounded-lg border px-3 py-2 font-mono text-sm" />
        </label>
        <label className="text-[10px] font-semibold text-slate-500">Y 좌표
          <input type="number" min="-4" max="8" step="0.01" value={Number.isFinite(destination.y) ? destination.y : ''} onChange={event => onDestinationChange({ ...destination, y: event.target.value === '' ? Number.NaN : Number(event.target.value) })} className="speed-input mt-1 w-full rounded-lg border px-3 py-2 font-mono text-sm" />
        </label>
        <div className="col-span-2 flex gap-2 sm:col-span-1">
          <button type="button" onClick={onSaveDestination} disabled={!destination.name.trim() || !Number.isFinite(destination.x) || !Number.isFinite(destination.y) || destination.x < -5 || destination.x > 5 || destination.y < -4 || destination.y > 8} className="secondary-button flex-1 rounded-lg border px-3 py-2.5 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50">좌표 저장</button>
          {status === 'navigating' ? (
            <button type="button" onClick={onStop} className="pilot-emergency flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-bold text-white"><Square size={13} /> 주행 중지</button>
          ) : (
          <button type="button" onClick={onStart} disabled={movementUnavailableReason !== null} title={movementUnavailableReason ?? undefined} className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"><Navigation size={14} /> 목적지로 이동</button>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-[var(--ui-muted)]">
        <button type="button" onClick={onSaveCurrentPosition} disabled={!currentPosition || !destination.name.trim()} className="rounded-lg border px-3 py-2 font-semibold text-[var(--ui-fg)] disabled:cursor-not-allowed disabled:opacity-50">현재 로봇 위치 저장</button>
        <span>{currentPosition ? destination.name.trim()
          ? `실제 위치 ${currentPosition.x.toFixed(2)}, ${currentPosition.y.toFixed(2)} m`
          : '현재 위치를 저장하려면 목적지 이름을 입력하세요.'
          : currentPositionUnavailableReason ?? '현재 위치 데이터 대기 중'}</span>
      </div>
      <div className="mt-3 text-[10px] text-[var(--ui-muted)]">{movementUnavailableReason ? `이동 버튼 비활성화: ${movementUnavailableReason}` : 'MuJoCo 상태·거리 센서 정상 · 목적지 준비 완료'} · 현재 위치 {currentPose.x.toFixed(2)}, {currentPose.y.toFixed(2)} m · 정적 장애물 지도 · A* 경로 계획</div>
      {status === 'navigating' && <div className="mt-2 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800"><span className="font-bold">현재 목표</span> · {destination.name} · X {destination.x.toFixed(2)} m, Y {destination.y.toFixed(2)} m</div>}
      {status === 'navigating' && plannedRoute.length > 0 && <div className="mt-1 text-[10px] font-semibold text-blue-700">장애물 회피 경로 · {plannedRoute.length}개 경유점</div>}
      {navigationNotice && <div role="status" className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{navigationNotice}</div>}
    </section>
  );
}
