import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

import app as app_module


pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def compile_cpp(source, output, *, static=False, libraries=()):
    command = [
        "g++",
        "-std=c++17",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
    ]
    if static:
        command.append("-static")
    command.extend([str(source), "-o", str(output)])
    # Libraries must follow the object that references them because the GNU
    # linker resolves archive symbols from left to right.
    command.extend(libraries)

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def linux_build(tmp_path_factory):
    if sys.platform != "linux":
        pytest.skip("the real Seccomp suite only runs on Linux")
    if shutil.which("g++") is None or not Path("/usr/include/seccomp.h").exists():
        pytest.skip("install g++ and libseccomp-dev to run integration tests")

    build_dir = tmp_path_factory.mktemp("aegis-linux-build")
    compile_cpp(
        PROJECT_ROOT / "sandbox_api.cpp",
        build_dir / "sandbox_api",
        libraries=("-lseccomp",),
    )
    compile_cpp(
        PROJECT_ROOT / "engine.cpp",
        build_dir / "engine_normal",
        static=True,
    )

    for source in sorted((PROJECT_ROOT / "tests" / "fixtures").glob("*.cpp")):
        compile_cpp(source, build_dir / source.stem, static=True)

    return build_dir


def prepare_runtime(tmp_path, linux_build, engine_name):
    runtime = tmp_path / engine_name
    runtime.mkdir()
    shutil.copy2(linux_build / "sandbox_api", runtime / "sandbox_api")
    shutil.copy2(linux_build / engine_name, runtime / "engine")
    return runtime


def call_api(monkeypatch, runtime, *, timeout=1.0):
    monkeypatch.setattr(app_module, "BASE_DIR", runtime)
    monkeypatch.setattr(app_module, "SANDBOX_BINARY", runtime / "sandbox_api")
    monkeypatch.setattr(app_module, "SANDBOX_TIMEOUT_SECONDS", timeout)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        return client.post("/api/v1/predict", json={"features": [1, -2, 3]})


def running_pids_for(executable):
    expected = executable.resolve()
    matches = []
    for process_dir in Path("/proc").glob("[0-9]*"):
        try:
            target = Path(os.readlink(process_dir / "exe")).resolve()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if target == expected:
            matches.append(int(process_dir.name))
    return matches


def test_real_engine_returns_prediction(tmp_path, linux_build, monkeypatch):
    runtime = prepare_runtime(tmp_path, linux_build, "engine_normal")
    response = call_api(monkeypatch, runtime)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"]["prediction"] == pytest.approx([2.3, 0.0])
    assert payload["execution"]["return_code"] == 0


@pytest.mark.parametrize("probe", ["forbidden_open", "forbidden_socket"])
def test_forbidden_syscall_is_reported_as_violation(
    tmp_path, linux_build, monkeypatch, probe
):
    runtime = prepare_runtime(tmp_path, linux_build, probe)
    response = call_api(monkeypatch, runtime)

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["error"]["code"] == "SANDBOX_VIOLATION"
    assert payload["execution"]["return_code"] == 128 + signal.SIGSYS


def test_infinite_loop_times_out_and_leaves_no_engine(
    tmp_path, linux_build, monkeypatch
):
    runtime = prepare_runtime(tmp_path, linux_build, "infinite_loop")

    started = time.monotonic()
    response = call_api(monkeypatch, runtime, timeout=0.2)
    elapsed = time.monotonic() - started

    assert response.status_code == 504
    payload = response.get_json()
    assert payload["error"]["code"] == "EXECUTION_TIMEOUT"
    assert payload["execution"]["return_code"] == -signal.SIGKILL
    assert elapsed < 1.5

    deadline = time.monotonic() + 1.0
    while running_pids_for(runtime / "engine") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert running_pids_for(runtime / "engine") == []


def test_output_flood_is_rejected(tmp_path, linux_build, monkeypatch):
    runtime = prepare_runtime(tmp_path, linux_build, "output_flood")
    response = call_api(monkeypatch, runtime)

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["error"]["code"] == "OUTPUT_LIMIT_EXCEEDED"


def test_missing_engine_is_fail_closed(tmp_path, linux_build, monkeypatch):
    runtime = tmp_path / "missing-engine"
    runtime.mkdir()
    shutil.copy2(linux_build / "sandbox_api", runtime / "sandbox_api")

    response = call_api(monkeypatch, runtime)

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["error"]["code"] == "SANDBOX_START_FAILED"
    assert payload["execution"]["return_code"] == 127
