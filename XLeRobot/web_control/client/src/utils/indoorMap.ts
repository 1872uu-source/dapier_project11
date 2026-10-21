import type { StaticObstacle } from './pathPlanner';
import destinationMap from '../../../shared/navigation_destinations.json';

/** MuJoCo test map expressed in the chassis/map frame used by /pose and scans. */
export const INDOOR_MAP = {
  source: 'mujoco_static' as const,
  frameId: 'xlerobot_map',
  resolution: 0.25,
  bounds: { minX: -5, maxX: 5, minY: -4, maxY: 8 },
  doorway: { wall: 'south', width: 1.8 },
  start: { x: 0, y: 0 },
  charging: { x: destinationMap.destinations[3].x, y: destinationMap.destinations[3].y },
  tables: [
    { name: '테이블 1', x: -2.45, y: 1.1, halfWidth: 0.7, halfHeight: 0.45, approach: { x: destinationMap.destinations[0].x, y: destinationMap.destinations[0].y } },
    { name: '테이블 2', x: 0, y: 3.0, halfWidth: 0.7, halfHeight: 0.45, approach: { x: destinationMap.destinations[1].x, y: destinationMap.destinations[1].y } },
    { name: '테이블 3', x: 2.45, y: 1.1, halfWidth: 0.7, halfHeight: 0.45, approach: { x: destinationMap.destinations[2].x, y: destinationMap.destinations[2].y } },
  ],
} as const;

export const INDOOR_STATIC_OBSTACLES: StaticObstacle[] = INDOOR_MAP.tables.map(table => ({
  name: table.name,
  x: table.x,
  y: table.y,
  halfWidth: table.halfWidth,
  halfHeight: table.halfHeight,
}));

export const TABLE_APPROACH_DESTINATIONS = INDOOR_MAP.tables.map(({ name, approach }) => ({
  name,
  ...approach,
}));

export const CHARGING_DESTINATION = {
  name: destinationMap.destinations[3].name,
  x: destinationMap.destinations[3].x,
  y: destinationMap.destinations[3].y,
};

export const NAVIGATION_DESTINATIONS = destinationMap.destinations;
