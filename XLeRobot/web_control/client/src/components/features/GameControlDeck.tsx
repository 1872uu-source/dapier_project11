import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { OctagonAlert, RotateCcw } from 'lucide-react';

type Vector = { x: number; y: number };

interface GameControlDeckProps {
  speed: number;
  onSpeedChange: (speed: number) => void;
  onJoystickMove: (vector: Vector) => void;
  onRotate: (direction: string) => void;
  onMoveStop: () => void;
  onEmergencyStop: () => void;
  onReset: () => void;
  connected: boolean;
}

export function GameControlDeck({ speed, onSpeedChange, onJoystickMove, onRotate, onMoveStop, onEmergencyStop, onReset, connected }: GameControlDeckProps) {
  const padRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef<HTMLDivElement>(null);
  const vectorRef = useRef<Vector>({ x: 0, y: 0 });
  const repeatRef = useRef<number | null>(null);
  const moveStopRef = useRef(onMoveStop);
  const joystickMoveRef = useRef(onJoystickMove);
  moveStopRef.current = onMoveStop;
  joystickMoveRef.current = onJoystickMove;
  const [speedDraft, setSpeedDraft] = useState(speed.toFixed(2));

  const updateStick = (event: PointerEvent<HTMLDivElement>) => {
    const pad = padRef.current;
    if (!pad) return;
    const rect = pad.getBoundingClientRect();
    const radius = Math.min(rect.width, rect.height) * 0.36;
    const rawX = (event.clientX - (rect.left + rect.width / 2)) / radius;
    const rawY = (event.clientY - (rect.top + rect.height / 2)) / radius;
    const magnitude = Math.hypot(rawX, rawY);
    const scale = magnitude > 1 ? 1 / magnitude : 1;
    const next = { x: rawX * scale, y: rawY * scale };
    vectorRef.current = Math.hypot(next.x, next.y) < 0.1 ? { x: 0, y: 0 } : next;
    if (stickRef.current) stickRef.current.style.transform = `translate(${vectorRef.current.x * radius}px, ${vectorRef.current.y * radius}px)`;
    onJoystickMove(vectorRef.current);
  };

  const release = () => {
    vectorRef.current = { x: 0, y: 0 };
    if (stickRef.current) stickRef.current.style.transform = 'translate(0px, 0px)';
    if (repeatRef.current !== null) window.clearInterval(repeatRef.current);
    repeatRef.current = null;
    onMoveStop();
    onJoystickMove(vectorRef.current);
  };

  const start = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    updateStick(event);
    if (repeatRef.current !== null) window.clearInterval(repeatRef.current);
    repeatRef.current = window.setInterval(() => onJoystickMove(vectorRef.current), 100);
  };

  useEffect(() => () => {
    if (repeatRef.current !== null) window.clearInterval(repeatRef.current);
    moveStopRef.current();
    joystickMoveRef.current({ x: 0, y: 0 });
  }, []);

  return (
    <section className="pilot-control-deck surface-card rounded-2xl border p-3 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="text-[10px] font-bold tracking-[0.24em] text-slate-500">조종 패널</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-semibold"><span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-amber-400'}`} />{connected ? 'MuJoCo 연결됨' : '로컬 시뮬레이션'}</div>
        </div>
        <label className="flex items-center gap-3 surface-subcard rounded-xl border px-3 py-2">
          <span><span className="block text-[9px] font-bold tracking-widest text-slate-500">최대 속도</span><span className="text-[10px] text-slate-600">0.00–1.00</span></span>
          <input aria-label="최대 이동 속도" type="number" min="0" max="1" step="0.01" value={speedDraft} onChange={event => { const draft = event.target.value; setSpeedDraft(draft); if (draft.trim() !== "") { const value = Number(draft); if (Number.isFinite(value) && value >= 0 && value <= 1) onSpeedChange(value); } }} onBlur={() => { const value = Number(speedDraft); const normalized = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : speed; onSpeedChange(normalized); setSpeedDraft(normalized.toFixed(2)); }} className="speed-input w-24 rounded-lg border px-2 py-2 text-right font-mono text-lg focus:outline-none" />
          <span className="font-mono text-xs text-slate-500">×</span>
        </label>
      </div>
      <div className="pilot-control-grid mt-3 flex flex-wrap items-center justify-between gap-4 border-t border-[var(--ui-card-border)] pt-3 sm:mt-4 sm:gap-6 sm:pt-4">
        <div className="pilot-joystick-group flex items-center gap-3 sm:gap-5">
          <div ref={padRef} onPointerDown={start} onPointerMove={event => { if (event.buttons > 0) updateStick(event); }} onPointerUp={release} onPointerCancel={release} className="pilot-joystick relative h-36 w-36 touch-none rounded-full border border-cyan-400/30 bg-[radial-gradient(circle,#1d3547_0%,#0b1520_72%)] shadow-[inset_0_0_24px_rgba(34,211,238,0.12)]">
            <span className="absolute left-1/2 top-2 -translate-x-1/2 text-[9px] font-bold text-slate-500">전진</span><span className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[9px] font-bold text-slate-500">후진</span><span className="absolute left-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-slate-500">◀</span><span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-slate-500">▶</span>
            <div ref={stickRef} className="pointer-events-none absolute left-1/2 top-1/2 h-12 w-12 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-cyan-200 bg-cyan-400/25 shadow-[0_0_18px_rgba(34,211,238,0.35)]" />
            <span className="pointer-events-none absolute -bottom-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] tracking-widest text-slate-500">터치해 이동</span>
          </div>
          <div className="pilot-rotate flex flex-col gap-2"><span className="text-[9px] font-bold tracking-[0.18em] text-slate-600">회전</span><button onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); onRotate('rotate_left'); if (repeatRef.current !== null) window.clearInterval(repeatRef.current); repeatRef.current = window.setInterval(() => onRotate('rotate_left'), 100); }} onPointerUp={release} onPointerCancel={release} className="secondary-button rounded-lg border px-3 py-2 font-mono text-xs">↶ 좌회전</button><button onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); onRotate('rotate_right'); if (repeatRef.current !== null) window.clearInterval(repeatRef.current); repeatRef.current = window.setInterval(() => onRotate('rotate_right'), 100); }} onPointerUp={release} onPointerCancel={release} className="secondary-button rounded-lg border px-3 py-2 font-mono text-xs">우회전 ↷</button></div>
        </div>
        <div className="pilot-actions flex items-center gap-2"><button onClick={() => { release(); onReset(); }} className="flex items-center gap-2 secondary-button rounded-lg border px-3 py-3 text-xs font-semibold"><RotateCcw size={15} /> 초기화</button><button onClick={() => { release(); onEmergencyStop(); }} className="pilot-emergency flex items-center justify-center gap-2 rounded-lg border border-rose-200 bg-rose-600 px-4 py-3 text-xs font-bold tracking-wide text-white shadow-sm hover:bg-rose-700"><OctagonAlert size={16} /> 긴급 정지</button></div>
      </div>
    </section>
  );
}
