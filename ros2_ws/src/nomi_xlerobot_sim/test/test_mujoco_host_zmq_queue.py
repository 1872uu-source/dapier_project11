import queue
import threading
import json
import unittest
from unittest.mock import Mock

import zmq

from nomi_xlerobot_sim.mujoco_host import XLeRobotMujocoHost


def make_host(sender):
    host = XLeRobotMujocoHost.__new__(XLeRobotMujocoHost)
    host.data_socket = sender
    host._command_response_queue = queue.Queue(maxsize=2)
    host._latest_state_response = None
    host._state_response_lock = threading.Lock()
    host._pending_zmq_response = None
    host._zmq_send_counters = {
        "sent": 0, "state_again": 0, "command_again": 0,
        "errors": 0, "queue_full": 0,
    }
    host._zmq_last_warning_at = 0.0
    host.get_logger = Mock(return_value=Mock())
    return host


class ZmqResponseQueueTests(unittest.TestCase):
    def test_no_receiver_drops_state_without_blocking(self):
        sender = Mock()
        sender.send_json.side_effect = zmq.Again()
        host = make_host(sender)
        host.send_response("state", {"x": 1})

        host._flush_zmq_responses()

        sender.send_json.assert_called_once()
        self.assertEqual(sender.send_json.call_args.kwargs["flags"], zmq.NOBLOCK)
        self.assertEqual(host._zmq_send_counters["state_again"], 1)
        self.assertIsNone(host._pending_zmq_response)

    def test_command_response_is_retained_and_retried(self):
        sender = Mock()
        sender.send_json.side_effect = [zmq.Again(), None]
        host = make_host(sender)
        host.send_response("success", {"status": "success"})

        host._flush_zmq_responses()
        self.assertIsNotNone(host._pending_zmq_response)
        self.assertEqual(host._zmq_send_counters["command_again"], 1)

        host._flush_zmq_responses()
        self.assertIsNone(host._pending_zmq_response)
        self.assertEqual(host._zmq_send_counters["sent"], 1)
        self.assertEqual(sender.send_json.call_count, 2)

    def test_command_responses_take_priority_and_protocol_is_preserved(self):
        sender = Mock()
        host = make_host(sender)
        host.send_response("state", {"x": 2})
        host.send_response("pong", {})

        host._flush_zmq_responses()

        sent = [call.args[0] for call in sender.send_json.call_args_list]
        self.assertEqual([item["response"] for item in sent], ["pong", "state"])
        self.assertTrue(all(item["type"] == "response" for item in sent))
        self.assertTrue(all("timestamp" in item and "data" in item for item in sent))
        self.assertEqual(sender.send_json.call_args.kwargs["flags"], zmq.NOBLOCK)

    def test_unexpected_send_error_is_counted_and_retained(self):
        sender = Mock()
        sender.send_json.side_effect = OSError("socket failure")
        host = make_host(sender)
        host.send_response("success", {})

        host._flush_zmq_responses()

        self.assertEqual(host._zmq_send_counters["errors"], 1)
        self.assertIsNotNone(host._pending_zmq_response)

    def test_state_snapshots_are_coalesced(self):
        sender = Mock()
        host = make_host(sender)
        host.send_response("state", {"x": 1})
        host.send_response("state", {"x": 2})

        host._flush_zmq_responses()

        sender.send_json.assert_called_once()
        self.assertEqual(sender.send_json.call_args.args[0]["data"], {"x": 2})

    def test_real_zmq_without_receiver_returns_again(self):
        context = zmq.Context()
        sender = context.socket(zmq.PUSH)
        sender.setsockopt(zmq.SNDHWM, 1)
        sender.setsockopt(zmq.LINGER, 0)
        sender.bind("inproc://nomi-no-receiver-test")
        host = make_host(sender)
        try:
            host.send_response("state", {"x": 1})
            host._flush_zmq_responses()
            self.assertEqual(host._zmq_send_counters["state_again"], 1)
        finally:
            sender.close(0)
            context.term()

    def test_real_zmq_full_receiver_buffer_returns_again(self):
        context = zmq.Context()
        sender = context.socket(zmq.PUSH)
        receiver = context.socket(zmq.PULL)
        sender.setsockopt(zmq.SNDHWM, 1)
        receiver.setsockopt(zmq.RCVHWM, 1)
        sender.setsockopt(zmq.LINGER, 0)
        receiver.setsockopt(zmq.LINGER, 0)
        endpoint = "inproc://nomi-full-buffer-test"
        receiver.bind(endpoint)
        sender.connect(endpoint)
        host = make_host(sender)
        try:
            for index in range(10):
                host.send_response("state", {"index": index})
                host._flush_zmq_responses()
            self.assertGreater(host._zmq_send_counters["state_again"], 0)
        finally:
            sender.close(0)
            receiver.close(0)
            context.term()

    def test_publish_state_keeps_ros_topic_publication(self):
        host = XLeRobotMujocoHost.__new__(XLeRobotMujocoHost)
        payload = {"status": "connected", "pose": {"x": 1.25}}
        host.current_state = Mock(return_value=payload)
        host.state_pub = Mock()
        host.send_response = Mock()

        host.publish_state()

        ros_message = host.state_pub.publish.call_args.args[0]
        self.assertEqual(json.loads(ros_message.data), payload)
        host.send_response.assert_called_once_with("state", payload)


if __name__ == "__main__":
    unittest.main()
