import { INDOOR_MAP, INDOOR_STATIC_OBSTACLES } from './indoorMap';

export interface RoutePoint {
  x: number;
  y: number;
}

export interface StaticObstacle {
  name: string;
  x: number;
  y: number;
  halfWidth: number;
  halfHeight: number;
}

export interface ScannedObstacle extends RoutePoint {
  distance?: number;
  source?: 'static' | 'dynamic';
}

// These footprints match the collidable table boxes in scene.xml.
export const STATIC_OBSTACLES: StaticObstacle[] = INDOOR_STATIC_OBSTACLES;

const WORLD = { ...INDOOR_MAP.bounds, resolution: INDOOR_MAP.resolution };
// Includes robot footprint, a safety margin, and half a grid cell diagonal.
const ROBOT_CLEARANCE = 0.8;
// A live scan point is on the obstacle surface. Use the same 1.0 m
// footprint margin in A* and route following so neither stage contradicts the other.
export const DYNAMIC_OBSTACLE_CLEARANCE = ROBOT_CLEARANCE + 0.2;
// The MuJoCo host accepts cardinal chassis-axis commands. A 4-connected grid
// keeps each followed segment on the exact path that was checked for clearance.
const DIRECTIONS = [[-1, 0, 1], [1, 0, 1], [0, -1, 1], [0, 1, 1]] as const;

class MinHeap {
  private values: Array<{ index: number; score: number }> = [];

  get size() { return this.values.length; }

  push(value: { index: number; score: number }) {
    this.values.push(value);
    let child = this.values.length - 1;
    while (child > 0) {
      const parent = Math.floor((child - 1) / 2);
      if (this.values[parent].score <= value.score) break;
      this.values[child] = this.values[parent];
      child = parent;
    }
    this.values[child] = value;
  }

  pop() {
    const first = this.values[0];
    const last = this.values.pop();
    if (this.values.length > 0 && last) {
      let parent = 0;
      while (true) {
        const left = parent * 2 + 1;
        const right = left + 1;
        if (left >= this.values.length) break;
        const child = right < this.values.length && this.values[right].score < this.values[left].score ? right : left;
        if (this.values[child].score >= last.score) break;
        this.values[parent] = this.values[child];
        parent = child;
      }
      this.values[parent] = last;
    }
    return first;
  }
}

/** Plan around the static scene and the latest live MuJoCo range scan. */
export function findRoute(
  start: RoutePoint,
  goal: RoutePoint,
  detectedObstacles: ScannedObstacle[] = [],
): RoutePoint[] | null {
  const columns = Math.round((WORLD.maxX - WORLD.minX) / WORLD.resolution) + 1;
  const rows = Math.round((WORLD.maxY - WORLD.minY) / WORLD.resolution) + 1;
  const total = columns * rows;
  const stateCount = total * 5;
  const startDirection = 4;
  const turnPenalty = 0.35;
  const toCell = ({ x, y }: RoutePoint) => ({
    x: Math.round((x - WORLD.minX) / WORLD.resolution),
    y: Math.round((y - WORLD.minY) / WORLD.resolution),
  });
  const toPoint = (cell: { x: number; y: number }): RoutePoint => ({
    x: WORLD.minX + cell.x * WORLD.resolution,
    y: WORLD.minY + cell.y * WORLD.resolution,
  });
  const indexOf = (x: number, y: number) => y * columns + x;
  const inBounds = (x: number, y: number) => x >= 0 && x < columns && y >= 0 && y < rows;
  const dynamicBlocked = new Uint8Array(total);
  const dynamicCellRadius = Math.ceil(DYNAMIC_OBSTACLE_CLEARANCE / WORLD.resolution);
  for (const obstacle of detectedObstacles.filter(item => item.source !== 'static')) {
    const center = toCell(obstacle);
    for (let dy = -dynamicCellRadius; dy <= dynamicCellRadius; dy += 1) {
      for (let dx = -dynamicCellRadius; dx <= dynamicCellRadius; dx += 1) {
        const x = center.x + dx;
        const y = center.y + dy;
        if (!inBounds(x, y)) continue;
        const point = toPoint({ x, y });
        if (Math.hypot(point.x - obstacle.x, point.y - obstacle.y) <= DYNAMIC_OBSTACLE_CLEARANCE) {
          dynamicBlocked[indexOf(x, y)] = 1;
        }
      }
    }
  }
  const blocked = (x: number, y: number) => {
    if (!inBounds(x, y)) return true;
    const point = toPoint({ x, y });
    return point.x < WORLD.minX + ROBOT_CLEARANCE || point.x > WORLD.maxX - ROBOT_CLEARANCE
      || point.y < WORLD.minY + ROBOT_CLEARANCE || point.y > WORLD.maxY - ROBOT_CLEARANCE
      || STATIC_OBSTACLES.some(obstacle =>
        Math.abs(point.x - obstacle.x) <= obstacle.halfWidth + ROBOT_CLEARANCE
        && Math.abs(point.y - obstacle.y) <= obstacle.halfHeight + ROBOT_CLEARANCE)
      || dynamicBlocked[indexOf(x, y)] === 1;
  };

  if (![start.x, start.y, goal.x, goal.y].every(Number.isFinite)) return null;
  if (start.x < WORLD.minX || start.x > WORLD.maxX || start.y < WORLD.minY || start.y > WORLD.maxY
    || goal.x < WORLD.minX || goal.x > WORLD.maxX || goal.y < WORLD.minY || goal.y > WORLD.maxY) return null;

  const startCell = toCell(start);
  const goalCell = toCell(goal);
  if (blocked(startCell.x, startCell.y) || blocked(goalCell.x, goalCell.y)) return null;

  const startIndex = indexOf(startCell.x, startCell.y);
  const goalIndex = indexOf(goalCell.x, goalCell.y);
  const costs = new Float64Array(stateCount).fill(Number.POSITIVE_INFINITY);
  const parents = new Int32Array(stateCount).fill(-1);
  const closed = new Uint8Array(stateCount);
  const queue = new MinHeap();
  const heuristic = (x: number, y: number) => Math.abs(goalCell.x - x) + Math.abs(goalCell.y - y);
  const startState = startIndex * 5 + startDirection;
  let goalState = startState;
  costs[startState] = 0;
  queue.push({ index: startState, score: heuristic(startCell.x, startCell.y) });

  while (queue.size > 0) {
    const current = queue.pop();
    if (!current || closed[current.index]) continue;
    const cellIndex = Math.floor(current.index / 5);
    const previousDirection = current.index % 5;
    if (cellIndex === goalIndex) {
      goalState = current.index;
      break;
    }
    closed[current.index] = 1;
    const x = cellIndex % columns;
    const y = Math.floor(cellIndex / columns);

    for (const [directionIndex, [dx, dy, stepCost]] of DIRECTIONS.entries()) {
      const nx = x + dx;
      const ny = y + dy;
      if (blocked(nx, ny)) continue;
      const nextState = indexOf(nx, ny) * 5 + directionIndex;
      const turnCost = previousDirection === startDirection || previousDirection === directionIndex ? 0 : turnPenalty;
      const nextCost = costs[current.index] + stepCost + turnCost;
      if (nextCost >= costs[nextState]) continue;
      costs[nextState] = nextCost;
      parents[nextState] = current.index;
      queue.push({ index: nextState, score: nextCost + heuristic(nx, ny) });
    }
  }

  if (startIndex !== goalIndex && goalState === startState) return null;
  const reversed: Array<{ x: number; y: number }> = [];
  for (let cursor = goalState; cursor !== startState; cursor = parents[cursor]) {
    if (cursor < 0) return null;
    const cellIndex = Math.floor(cursor / 5);
    reversed.push({ x: cellIndex % columns, y: Math.floor(cellIndex / columns) });
  }
  reversed.reverse();
  if (reversed.length === 0) return [{ ...goal }];

  // Keep only corners so the robot follows smooth straight segments instead
  // of stopping at every half-meter grid cell.
  const turns: Array<{ x: number; y: number }> = [];
  for (let i = 0; i < reversed.length; i += 1) {
    const previous = i === 0 ? startCell : reversed[i - 1];
    const current = reversed[i];
    const next = reversed[i + 1];
    if (!next || current.x - previous.x !== next.x - current.x || current.y - previous.y !== next.y - current.y) {
      turns.push(current);
    }
  }
  const points = turns.map(cell => toPoint(cell));
  const finalPoint = points[points.length - 1];
  if (!finalPoint || Math.hypot(finalPoint.x - goal.x, finalPoint.y - goal.y) > 0.05) points.push({ ...goal });
  return points;
}

/** Only mobile returns belong in live re-planning; static geometry is already in the map. */
export function getDynamicObstaclePoints(scan: ScannedObstacle[]): RoutePoint[] {
  return scan
    .filter(point => point.source !== 'static' && Number.isFinite(point.x) && Number.isFinite(point.y))
    .map(({ x, y }) => ({ x, y }));
}

/** Check the remaining route against dynamic scan points using A*'s exact margin. */
export function isRouteBlockedByDynamicObstacle(
  pose: RoutePoint,
  route: RoutePoint[],
  waypointIndex: number,
  obstacles: RoutePoint[],
): boolean {
  const points = [pose, ...route.slice(waypointIndex)];
  return obstacles.some(obstacle => points.slice(1).some((end, index) => {
    const start = points[index];
    const vx = end.x - start.x;
    const vy = end.y - start.y;
    const lengthSquared = vx * vx + vy * vy;
    const t = lengthSquared > 0
      ? Math.max(0, Math.min(1, ((obstacle.x - start.x) * vx + (obstacle.y - start.y) * vy) / lengthSquared))
      : 0;
    return Math.hypot(obstacle.x - (start.x + t * vx), obstacle.y - (start.y + t * vy)) < DYNAMIC_OBSTACLE_CLEARANCE;
  }));
}
