#!/usr/bin/env node
// Live integration: Socket.IO -> FastAPI -> ZMQ -> MuJoCo Host -> state feedback.
// Run only with the isolated MuJoCo Host and backend on ROS_DOMAIN_ID=222.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { io } from 'socket.io-client';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = path.resolve('src/utils');
function loadTs(name, dependencies = {}) {
  const source = fs.readFileSync(path.join(root, `${name}.ts`), 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output)(
    id => dependencies[id] ?? (() => { throw new Error(`unexpected import ${id}`); })(),
    module,
    module.exports,
  );
  return module.exports;
}
const map = loadTs('indoorMap');
const planner = loadTs('pathPlanner', { './indoorMap': map });
const controller = loadTs('navigationController');

const destinations = {
  table_1: { name: '테이블 1', x: -2.45, y: -0.4 },
  table_2: { name: '테이블 2', x: 0, y: 1.5 },
  table_3: { name: '테이블 3', x: 2.45, y: -0.4 },
  charging: { name: '충전 위치', x: -3.8, y: 6.8 },
};
const selected = process.argv.slice(2).length ? process.argv.slice(2) : ['table_1', 'table_2', 'table_3'];
for (const name of selected) if (!destinations[name]) throw new Error(`unknown target: ${name}`);

const serverUrl = process.env.NOMI_TEST_SERVER_URL || 'http://127.0.0.1:8000';
const requestedTestSpeed = Number(process.env.NOMI_TEST_SPEED ?? 0.35);
if (!Number.isFinite(requestedTestSpeed) || requestedTestSpeed <= 0 || requestedTestSpeed > 1) {
  throw new Error('NOMI_TEST_SPEED must be greater than 0 and at most 1.0 m/s');
}
const socket = io(serverUrl, { transports: ['websocket'], reconnection: false, timeout: 5000 });
let latestState;
const acks = new Map();
const stateWaiters = [];
const ackWaiters = new Map();
let sequence = 0;
let lastStateAt = 0;
let serverGaps = [];
let ackLatencies = [];
let velocitySamples = [];
let collectVelocity = false;
socket.on('robot_state_snapshot', payload => {
  if (payload?.state) {
    latestState = payload.state;
    const now = performance.now();
    if (lastStateAt) serverGaps.push(now - lastStateAt);
    lastStateAt = now;
    if (collectVelocity) {
      const vx = Number(payload.state.velocity?.linear?.x);
      const vy = Number(payload.state.velocity?.linear?.y);
      if (Number.isFinite(vx) && Number.isFinite(vy)) velocitySamples.push(Math.hypot(vx, vy));
    }
    stateWaiters.splice(0).forEach(resolve => resolve());
  }
});
socket.on('command_received', payload => {
  if (typeof payload?.sequence !== 'number') return;
  const sentAt = acks.get(payload.sequence);
  if (sentAt !== undefined) {
    ackLatencies.push(performance.now() - sentAt);
    acks.delete(payload.sequence);
  }
  ackWaiters.get(payload.sequence)?.(payload);
  ackWaiters.delete(payload.sequence);
});
let resetAcknowledged = false;
socket.on('robot_reset_result', () => { resetAcknowledged = true; });

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitForState(timeoutMs = 5000) {
  const deadline = performance.now() + timeoutMs;
  while (!latestState && performance.now() < deadline) {
    await Promise.race([new Promise(resolve => stateWaiters.push(resolve)), delay(100)]);
  }
  if (!latestState) throw new Error('no robot_state_snapshot received');
  return latestState;
}
function poseOf(state) {
  return {
    x: Number(state?.position?.x),
    y: Number(state?.position?.y),
    yaw: Number(state?.rotation?.yaw),
  };
}
async function sendAndVerifyStop() {
  await sendAndCheck('stop', 0, 0, 0, 0);
  const deadline = performance.now() + 5000;
  let measured;
  while (performance.now() < deadline) {
    const linear = latestState?.velocity?.linear || {};
    const angular = Number(latestState?.velocity?.angular?.z ?? 0);
    measured = {
      linear_mps: Math.hypot(Number(linear.x ?? 0), Number(linear.y ?? 0)),
      yaw_rate_rad_s: Math.abs(angular),
    };
    if (measured.linear_mps <= 0.05 && measured.yaw_rate_rad_s <= 0.05) return measured;
    await delay(50);
  }
  throw new Error(`MuJoCo did not settle after stop command: ${JSON.stringify(measured)}`);
}
function assertNavigationState(state) {
  const status = state?.obstacle_scan_status || {};
  if (state?.robot_type !== 'mujoco' || state?.host_connected !== true
      || state?.navigation_execution_enabled !== true || state?.nomi_mock_mode === true
      || !Number.isFinite(state?.state_age) || state.state_age > 2.5
      || status.healthy !== true || !Number.isFinite(status.age_ms) || status.age_ms > 1200
      || !Array.isArray(state?.obstacle_scan)) {
    throw new Error(`navigation safety gate failed: ${JSON.stringify({
      robot_type: state?.robot_type, host_connected: state?.host_connected,
      navigation_execution_enabled: state?.navigation_execution_enabled,
      state_age: state?.state_age, scan_healthy: status.healthy,
      scan_age_ms: status.age_ms,
    })}`);
  }
}
function sendMove(direction, speed, angular, linearX, linearY) {
  const current = ++sequence;
  const sentAt = performance.now();
  acks.set(current, sentAt);
  socket.emit('move_command', {
    direction, speed, angular, linear_x: linearX, linear_y: linearY,
    sequence: current, timestamp: Date.now(),
  });
  return { sequence: current, sentAt };
}
async function sendAndCheck(direction, speed, angular, linearX, linearY) {
  const sent = sendMove(direction, speed, angular, linearX, linearY);
  const response = await Promise.race([
    new Promise(resolve => ackWaiters.set(sent.sequence, resolve)),
    delay(1500).then(() => null),
  ]);
  if (!response) throw new Error(`no Socket.IO command_received for sequence ${sent.sequence}`);
  const expectedStatus = direction === 'drive_vector' ? 'queued_to_zmq' : 'success';
  if (response.status !== expectedStatus) {
    throw new Error(`sequence ${sent.sequence} not accepted by ZMQ queue: ${JSON.stringify(response)}`);
  }
  return response;
}

try {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Socket.IO connect timeout')), 6000);
    socket.once('connect', () => { clearTimeout(timer); resolve(); });
    socket.once('connect_error', error => { clearTimeout(timer); reject(error); });
  });
  await waitForState();
  socket.emit('reset_robot');
  const resetDeadline = performance.now() + 5000;
  while (performance.now() < resetDeadline) {
    const pose = poseOf(latestState);
    if (resetAcknowledged && Math.hypot(pose.x, pose.y) < 0.05 && Math.abs(pose.yaw) < 0.05) break;
    await delay(50);
  }
  const resetPose = poseOf(latestState);
  if (!resetAcknowledged || Math.hypot(resetPose.x, resetPose.y) >= 0.05 || Math.abs(resetPose.yaw) >= 0.05) {
    throw new Error(`MuJoCo reset could not be confirmed: ${JSON.stringify({ resetAcknowledged, resetPose })}`);
  }
  console.log(JSON.stringify({
    event: 'connected', server: serverUrl, sid: socket.id,
    robot_type: latestState.robot_type, host_connected: latestState.host_connected,
    navigation_execution_enabled: latestState.navigation_execution_enabled,
    state_age_s: latestState.state_age,
    scan_healthy: latestState.obstacle_scan_status?.healthy,
    scan_age_ms: latestState.obstacle_scan_status?.age_ms,
    pose: poseOf(latestState),
  }));

  for (const targetName of selected) {
    serverGaps = [];
    ackLatencies = [];
    velocitySamples = [];
    collectVelocity = true;
    lastStateAt = 0;
    assertNavigationState(latestState);
    const target = destinations[targetName];
    const initialPose = poseOf(latestState);
    let route = planner.findRoute(initialPose, target, planner.getDynamicObstaclePoints(latestState.obstacle_scan));
    if (!route?.length) throw new Error(`${target.name}: A* returned no route from ${JSON.stringify(initialPose)}`);
    let waypointIndex = 0;
    let turnDirection = null;
    const motionGuard = new controller.NavigationMotionGuard();
    let ticks = 0;
    let lastCommandAt = 0;
    const commandGaps = [];
    const commands = [];
    const started = performance.now();
    while (waypointIndex < route.length && ticks < 900) {
      assertNavigationState(latestState);
      const pose = poseOf(latestState);
      const waypoint = route[waypointIndex];
      const distance = Math.hypot(waypoint.x - pose.x, waypoint.y - pose.y);
      const actualYawRate = Number(latestState.velocity?.angular?.z ?? 0);
      if (distance <= 0.3 && Math.abs(actualYawRate) <= 0.05) {
        waypointIndex += 1;
        turnDirection = null;
        motionGuard.reset();
        await sendAndCheck('stop', 0, 0, 0, 0);
        await delay(100); // Match the React follower's 100 ms timer after waypoint state changes.
        continue;
      }
      const dynamic = planner.getDynamicObstaclePoints(latestState.obstacle_scan);
      if (planner.isRouteBlockedByDynamicObstacle(pose, route, waypointIndex, dynamic)) {
        route = planner.findRoute(pose, target, dynamic);
        if (!route?.length) throw new Error(`${target.name}: dynamic obstacle blocked route; safe reroute unavailable`);
        waypointIndex = 0;
        turnDirection = null;
        motionGuard.reset();
        await sendAndCheck('stop', 0, 0, 0, 0);
        await delay(100);
        continue;
      }
      const command = controller.computeWaypointCommand(pose, waypoint, requestedTestSpeed, turnDirection, actualYawRate);
      turnDirection = command.turnDirection;
      const actualLinear = latestState.velocity?.linear || {};
      const motionFault = motionGuard.observe({
        nowMs: performance.now(),
        distance,
        commandedX: command.linearX,
        commandedY: command.linearY,
        actualX: Number(actualLinear.x ?? 0),
        actualY: Number(actualLinear.y ?? 0),
        commandedAngular: command.angular,
        actualAngular: actualYawRate,
        damping: command.damping,
      });
      if (motionFault) {
        await sendAndVerifyStop();
        throw new Error(`${target.name}: NavigationMotionGuard stopped route: ${motionFault}`);
      }
      const now = performance.now();
      if (lastCommandAt) commandGaps.push(now - lastCommandAt);
      lastCommandAt = now;
      const ack = await sendAndCheck(
        'drive_vector', Math.hypot(command.linearX, command.linearY), command.angular,
        command.linearX, command.linearY,
      );
      commands.push({ sequence: ack.sequence, speed: Math.hypot(command.linearX, command.linearY), angular: command.angular, actual_angular: actualYawRate, phase: command.phase });
      ticks += 1;
      await delay(Math.max(0, 100 - (performance.now() - now)));
    }
    if (waypointIndex < route.length) throw new Error(`${target.name}: controller timed out at waypoint ${waypointIndex}/${route.length}`);
    const stopResult = await sendAndVerifyStop();
    const finalPose = poseOf(latestState);
    const error = Math.hypot(target.x - finalPose.x, target.y - finalPose.y);
    const report = {
      event: 'destination_result', target: target.name, route_waypoints: route.length,
      requested_max_speed_mps: requestedTestSpeed,
      command_count: commands.length, initial_pose: initialPose, final_pose: finalPose,
      destination: { x: target.x, y: target.y }, arrival_error_m: error,
      duration_s: Number(((performance.now() - started) / 1000).toFixed(2)),
      command_gap_ms: summarize(commandGaps), socket_ack_ms: summarize(ackLatencies),
      state_snapshot_gap_ms: summarize(serverGaps), max_speed_mps: Math.max(0, ...commands.map(c => c.speed)),
      actual_speed_mps: {
        samples: velocitySamples.length,
        average: velocitySamples.length ? Number((velocitySamples.reduce((a, b) => a + b, 0) / velocitySamples.length).toFixed(3)) : null,
        max: velocitySamples.length ? Number(Math.max(...velocitySamples).toFixed(3)) : null,
      },
      max_abs_angular_rad_s: Math.max(0, ...commands.map(c => Math.abs(c.angular))),
      motion_guard: 'no_fault',
      verified_stop: stopResult,
      all_socket_responses_queued_to_zmq: true,
    };
    console.log(JSON.stringify(report));
    collectVelocity = false;
    if (error > 0.3) throw new Error(`${target.name}: route ended outside 0.3m arrival radius (${error.toFixed(3)}m)`);
  }
} catch (error) {
  try { sendMove('stop', 0, 0, 0, 0); } catch { /* best-effort safe stop */ }
  console.error(JSON.stringify({ event: 'failure', message: String(error) }));
  process.exitCode = 1;
} finally {
  socket.disconnect();
}

function summarize(values) {
  if (!values.length) return { count: 0, avg: null, max: null };
  return {
    count: values.length,
    avg: Number((values.reduce((a, b) => a + b, 0) / values.length).toFixed(2)),
    max: Number(Math.max(...values).toFixed(2)),
  };
}
