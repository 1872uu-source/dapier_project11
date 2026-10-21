import { io } from 'socket.io-client';
import readline from 'node:readline';

const url = process.argv[2];
const sockets = { primary: io(url, { transports: ['websocket'], reconnection: false, timeout: 10000 }) };
const out = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);

function attach(socket, clientId) {
  socket.on('connect', () => out({ type: 'connected', client_id: clientId, sid: socket.id }));
  socket.on('connect_error', (error) => out({ type: 'client_error', client_id: clientId, error: String(error?.message ?? error) }));
  for (const event of [
    'nomi_task_status', 'nomi_model_status', 'nomi_bridge_status', 'nomi_response',
    'nomi_cancel_result', 'nomi_command_received', 'nomi_error',
  ]) {
    socket.on(event, (payload) => out({ type: 'event', client_id: clientId, event, payload }));
  }
}
attach(sockets.primary, 'primary');

const lines = readline.createInterface({ input: process.stdin });
lines.on('line', (raw) => {
  try {
    const message = JSON.parse(raw);
    if (message.event === '__close') {
      Object.values(sockets).forEach((socket) => socket.disconnect());
      process.exit(0);
    }
    if (message.event === '__connect_secondary') {
      sockets.secondary = io(url, { transports: ['websocket'], reconnection: false, timeout: 10000 });
      attach(sockets.secondary, 'secondary');
      return;
    }
    const socket = sockets[message.client_id ?? 'primary'];
    if (!socket) throw new Error(`unknown Socket.IO client ${message.client_id}`);
    if (Object.hasOwn(message, 'payload')) socket.emit(message.event, message.payload);
    else socket.emit(message.event);
  } catch (error) {
    out({ type: 'client_error', error: String(error) });
  }
});
