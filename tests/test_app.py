import json
import signal
import subprocess

import pytest

import app as app_module


SUCCESS_STDOUT = (
    "[Aegis Sandbox] starting\n"
    '{"status":"success","prediction":[2.3,0]}\n'
    "[Aegis-Parent] finished\n"
)


@pytest.fixture
def client():
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def post_json(client, payload):
    return client.post(
        "/api/v1/predict",
        data=json.dumps(payload, allow_nan=True),
        content_type="application/json",
    )


def install_fake_process(
    monkeypatch,
    *,
    stdout=SUCCESS_STDOUT,
    stderr="",
    stdout_seek_to=None,
    returncode=0,
    times_out=False,
    launch_error=None,
):
    state = {}

    class FakeProcess:
        pid = 424242

        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs
            self.returncode = None if times_out else returncode
            self.input = None
            self.waited = False
            self.killed = False

        def communicate(self, *, input, timeout):
            self.input = input
            self.timeout = timeout
            if times_out:
                raise subprocess.TimeoutExpired(self.command, timeout)
            self.kwargs["stdout"].write(stdout.encode())
            self.kwargs["stderr"].write(stderr.encode())
            if stdout_seek_to is not None:
                self.kwargs["stdout"].seek(stdout_seek_to)

        def wait(self, timeout=None):
            self.waited = True
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -signal.SIGKILL

    def fake_popen(command, **kwargs):
        if launch_error is not None:
            raise launch_error
        process = FakeProcess(command, **kwargs)
        state["process"] = process
        return process

    monkeypatch.setattr(app_module.subprocess, "Popen", fake_popen)
    return state


def assert_error(response, http_status, error_code):
    assert response.status_code == http_status
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == error_code
    assert isinstance(payload["sandbox_logs"], list)
    return payload


def test_successful_prediction_uses_expected_process_contract(client, monkeypatch):
    state = install_fake_process(monkeypatch, stderr="diagnostic\n")

    response = post_json(client, {"features": [1, -2, 3]})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"]["prediction"] == [2.3, 0]
    assert payload["execution"]["return_code"] == 0
    assert payload["sandbox_logs"] == [
        "[Aegis Sandbox] starting",
        "[Aegis-Parent] finished",
        "[stderr] diagnostic",
    ]

    process = state["process"]
    assert process.command == [str(app_module.SANDBOX_BINARY)]
    assert process.kwargs["cwd"] == app_module.BASE_DIR
    assert process.kwargs["start_new_session"] is True
    assert process.kwargs["close_fds"] is True
    assert process.kwargs["env"] == {}
    assert process.input == b"1 -2 3\n"
    assert process.timeout == app_module.SANDBOX_TIMEOUT_SECONDS


def test_only_post_is_allowed(client):
    assert_error(client.get("/api/v1/predict"), 405, "METHOD_NOT_ALLOWED")


def test_unknown_route_uses_json_error(client):
    assert_error(client.get("/does-not-exist"), 404, "NOT_FOUND")


def test_content_type_must_be_json(client):
    response = client.post("/api/v1/predict", data="1 -2 3")
    assert_error(response, 415, "UNSUPPORTED_MEDIA_TYPE")


def test_malformed_json_is_rejected(client):
    response = client.post(
        "/api/v1/predict",
        data="{broken",
        content_type="application/json",
    )
    assert_error(response, 400, "INVALID_INPUT")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"features": [1, 2]},
        {"features": [1, 2, 3, 4]},
        {"features": ["1", 2, 3]},
        {"features": [True, 2, 3]},
        {"features": [None, 2, 3]},
        {"features": [{}, 2, 3]},
        {"features": [1_000_001, 2, 3]},
        {"features": [float("nan"), 2, 3]},
        {"features": [float("inf"), 2, 3]},
        {"features": [float("-inf"), 2, 3]},
    ],
)
def test_invalid_features_are_rejected_before_process_launch(
    client, monkeypatch, payload
):
    def unexpected_popen(*_args, **_kwargs):
        pytest.fail("invalid input must not launch the sandbox")

    monkeypatch.setattr(app_module.subprocess, "Popen", unexpected_popen)
    assert_error(post_json(client, payload), 400, "INVALID_INPUT")


def test_large_integer_is_rejected_before_process_launch(client, monkeypatch):
    payload = {"features": [int("9" * 309), 2, 3]}
    encoded_payload = json.dumps(payload).encode()
    assert len(encoded_payload) < app_module.app.config["MAX_CONTENT_LENGTH"]

    def unexpected_popen(*_args, **_kwargs):
        pytest.fail("invalid input must not launch the sandbox")

    monkeypatch.setattr(app_module.subprocess, "Popen", unexpected_popen)
    assert_error(post_json(client, payload), 400, "INVALID_INPUT")


def test_request_body_is_limited_to_four_kib(client):
    response = post_json(
        client,
        {"features": [1, 2, 3], "padding": "x" * 5000},
    )
    assert_error(response, 413, "REQUEST_TOO_LARGE")


@pytest.mark.parametrize(
    ("returncode", "http_status", "error_code"),
    [
        (128 + signal.SIGSYS, 422, "SANDBOX_VIOLATION"),
        (127, 503, "SANDBOX_START_FAILED"),
        (-signal.SIGSEGV, 502, "SANDBOX_CRASHED"),
        (7, 422, "ENGINE_FAILED"),
    ],
)
def test_process_failures_have_stable_error_codes(
    client, monkeypatch, returncode, http_status, error_code
):
    install_fake_process(
        monkeypatch,
        stdout="sandbox log\n",
        returncode=returncode,
    )
    response = post_json(client, {"features": [1, 2, 3]})
    payload = assert_error(response, http_status, error_code)
    assert payload["execution"]["return_code"] == returncode


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "{broken json\n",
        (
            '{"status":"success","prediction":[1,2]}\n'
            '{"status":"success","prediction":[3,4]}\n'
        ),
        '{"status":"error","prediction":[1,2]}\n',
        '{"status":"success","prediction":[1]}\n',
        '{"status":"success","prediction":[true,2]}\n',
        '{"status":"success","prediction":[NaN,2]}\n',
    ],
)
def test_invalid_engine_protocol_never_becomes_http_200(
    client, monkeypatch, stdout
):
    install_fake_process(monkeypatch, stdout=stdout)
    response = post_json(client, {"features": [1, 2, 3]})
    assert_error(response, 502, "SANDBOX_PROTOCOL_ERROR")


def test_large_integer_in_engine_prediction_is_protocol_error(client, monkeypatch):
    stdout = (
        '{"status":"success","prediction":['
        + "9" * 309
        + ",0]}\n"
    )
    install_fake_process(monkeypatch, stdout=stdout)

    response = post_json(client, {"features": [1, 2, 3]})

    assert_error(response, 502, "SANDBOX_PROTOCOL_ERROR")


def test_deeply_nested_engine_json_is_protocol_error(client, monkeypatch):
    depth = 10_000
    stdout = (
        '{"status":"success","prediction":[1,2],"nested":'
        + "[" * depth
        + "0"
        + "]" * depth
        + "}\n"
    )
    assert len(stdout.encode()) < app_module.MAX_OUTPUT_BYTES
    install_fake_process(monkeypatch, stdout=stdout)

    response = post_json(client, {"features": [1, 2, 3]})

    assert_error(response, 502, "SANDBOX_PROTOCOL_ERROR")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_over_limit_is_rejected(client, monkeypatch, stream):
    kwargs = {stream: "x" * (app_module.MAX_OUTPUT_BYTES + 1)}
    install_fake_process(monkeypatch, **kwargs)
    response = post_json(client, {"features": [1, 2, 3]})
    assert_error(response, 422, "OUTPUT_LIMIT_EXCEEDED")


def test_output_limit_uses_file_size_not_current_offset(client, monkeypatch):
    install_fake_process(
        monkeypatch,
        stdout="x" * (app_module.MAX_OUTPUT_BYTES + 1),
        stdout_seek_to=1,
    )

    response = post_json(client, {"features": [1, 2, 3]})

    assert_error(response, 422, "OUTPUT_LIMIT_EXCEEDED")


def test_exact_output_limit_is_allowed(client, monkeypatch):
    result = '{"status":"success","prediction":[1,2]}\n'
    padding = "x" * (app_module.MAX_OUTPUT_BYTES - len(result) - 1) + "\n"
    install_fake_process(monkeypatch, stdout=padding + result)
    response = post_json(client, {"features": [1, 2, 3]})
    assert response.status_code == 200


def test_missing_sandbox_binary_returns_service_unavailable(client, monkeypatch):
    install_fake_process(
        monkeypatch,
        launch_error=FileNotFoundError(2, "No such file or directory"),
    )
    response = post_json(client, {"features": [1, 2, 3]})
    assert_error(response, 503, "SANDBOX_UNAVAILABLE")


def test_timeout_kills_the_process_group(client, monkeypatch):
    state = install_fake_process(monkeypatch, times_out=True)
    killed = {}

    def fake_kill_process_group(process):
        killed["pid"] = process.pid
        process.returncode = -signal.SIGKILL
        process.wait()

    monkeypatch.setattr(app_module, "kill_process_group", fake_kill_process_group)

    response = post_json(client, {"features": [1, 2, 3]})
    payload = assert_error(response, 504, "EXECUTION_TIMEOUT")
    assert killed["pid"] == state["process"].pid
    assert state["process"].waited is True
    assert payload["execution"]["return_code"] == -signal.SIGKILL
