"""Safety checks for the local outage controller; no IIS or Docker required."""

import importlib.util
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, Request


SPEC = importlib.util.spec_from_file_location("lab_controller", Path(__file__).with_name("app.py"))
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class LabControllerTests(unittest.TestCase):
    def test_frontend_stop_and_restore_moves_only_its_index(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            disabled = Path(directory) / "index.html.lab-disabled"
            unrelated = Path(directory) / "other.html"
            index.write_text("test app", encoding="utf-8")
            unrelated.write_text("other app", encoding="utf-8")
            with patch.object(lab, "INDEX", index), patch.object(lab, "DISABLED_INDEX", disabled):
                control = lab.LabController()
                control.stop_frontend()
                self.assertFalse(index.exists())
                self.assertEqual(disabled.read_text(encoding="utf-8"), "test app")
                control.start_frontend()
                self.assertEqual(index.read_text(encoding="utf-8"), "test app")
                self.assertFalse(disabled.exists())
                self.assertEqual(unrelated.read_text(encoding="utf-8"), "other app")

    def test_database_commands_target_only_postgres(self):
        control = lab.LabController()
        control._compose = Mock(return_value="")
        control.stop_database()
        control.start_database()
        self.assertEqual(control._compose.call_args_list, [
            unittest.mock.call("stop", "postgres"),
            unittest.mock.call("up", "-d", "postgres"),
        ])

    def test_route_simulation_changes_only_the_test_proxy_and_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = Path(directory) / "web.config"
            backup = Path(directory) / "web.config.lab-original"
            original = f'<rewrite url="{lab.PROXY_TARGET}" /><unrelated>keep</unrelated>'
            configuration.write_text(original, encoding="utf-8")
            with patch.object(lab, "PROXY_CONFIG", configuration), patch.object(lab, "PROXY_BACKUP", backup):
                control = lab.LabController()
                control.stop_route()
                self.assertIn(lab.BROKEN_TARGET, configuration.read_text(encoding="utf-8"))
                self.assertEqual(backup.read_text(encoding="utf-8"), original)
                control.start_route()
                self.assertEqual(configuration.read_text(encoding="utf-8"), original)
                self.assertFalse(backup.exists())

    def test_disk_restore_removes_only_its_own_file(self):
        with tempfile.TemporaryDirectory() as directory:
            load = Path(directory) / "lab-disk-load.bin"
            unrelated = Path(directory) / "inventory.txt"
            load.write_bytes(b"test")
            unrelated.write_text("keep", encoding="utf-8")
            with patch.object(lab, "DISK_LOAD", load):
                lab.LabController().stop_disk()
            self.assertFalse(load.exists())
            self.assertTrue(unrelated.exists())

    def test_api_stop_requires_controller_owned_process(self):
        control = lab.LabController()
        with self.assertRaisesRegex(RuntimeError, "does not own"):
            control.stop_api()
        process = Mock()
        process.poll.return_value = None
        control.api_process = process
        control.stop_api()
        process.terminate.assert_called_once()
        self.assertIsNone(control.api_process)

    def test_api_start_refuses_an_existing_listener(self):
        control = lab.LabController()
        with patch.object(control, "_port_busy", return_value=True), patch.object(lab.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "Port 8008 is occupied"):
                control.start_api()
            popen.assert_not_called()

    def test_api_start_uses_only_the_test_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            control = lab.LabController()
            with patch.object(lab, "API_LOG", Path(directory) / "api-console.log"), \
                 patch.object(control, "_port_busy", return_value=False), \
                 patch.object(control, "_api_responding", return_value=True), \
                 patch.object(lab.subprocess, "Popen") as popen:
                popen.return_value.poll.return_value = None
                control.start_api()
                command = popen.call_args.args[0]
                self.assertEqual(command[1:5], ["-m", "uvicorn", "app:app", "--app-dir"])
                self.assertEqual(command[5], "backend")
                self.assertEqual(popen.call_args.kwargs["cwd"], lab.ROOT)

    def test_mutation_rejects_foreign_origin(self):
        request = Request({"type": "http", "headers": [(b"origin", b"http://other.example")]})
        with self.assertRaises(HTTPException) as result:
            lab.change_state("database", "stop", request, "local-lab").send(None)
        self.assertEqual(result.exception.status_code, 403)

    def test_remote_control_requires_correct_basic_credentials(self):
        def request(authorization=None):
            headers = [] if authorization is None else [(b"authorization", authorization.encode("ascii"))]
            return Request({"type": "http", "headers": headers})

        with patch.dict(lab.os.environ, {"LAB_CONTROL_USER": "admin", "LAB_CONTROL_PASSWORD": "private-test-value"}):
            with self.assertRaises(HTTPException) as missing:
                lab.require_remote_auth(request())
            self.assertEqual(missing.exception.status_code, 401)
            wrong = "Basic " + base64.b64encode(b"admin:wrong").decode("ascii")
            with self.assertRaises(HTTPException) as invalid:
                lab.require_remote_auth(request(wrong))
            self.assertEqual(invalid.exception.status_code, 401)
            valid = "Basic " + base64.b64encode(b"admin:private-test-value").decode("ascii")
            self.assertIsNone(lab.require_remote_auth(request(valid)))

    def test_remote_control_fails_closed_without_server_secret(self):
        with patch.dict(lab.os.environ, {"LAB_CONTROL_USER": "admin", "LAB_CONTROL_PASSWORD": "replace-me"}):
            with self.assertRaises(HTTPException) as result:
                lab.require_remote_auth(Request({"type": "http", "headers": []}))
            self.assertEqual(result.exception.status_code, 503)

    def test_remote_mutation_requires_custom_header_after_auth(self):
        auth = "Basic " + base64.b64encode(b"admin:private-test-value").decode("ascii")
        missing = Request({"type": "http", "headers": [(b"authorization", auth.encode("ascii"))]})
        allowed = Request({"type": "http", "headers": [
            (b"authorization", auth.encode("ascii")), (b"x-lab-control", b"remote-lab")
        ]})
        with patch.dict(lab.os.environ, {"LAB_CONTROL_USER": "admin", "LAB_CONTROL_PASSWORD": "private-test-value"}), \
             patch.object(lab, "perform_change", new_callable=AsyncMock) as operation:
            with self.assertRaises(HTTPException) as denied:
                lab.remote_change_state("api", "stop", missing).send(None)
            self.assertEqual(denied.exception.status_code, 403)
            operation.assert_not_called()
            with self.assertRaises(StopIteration):
                lab.remote_change_state("api", "stop", allowed).send(None)
            operation.assert_awaited_once_with("api", "stop")


if __name__ == "__main__":
    unittest.main()
