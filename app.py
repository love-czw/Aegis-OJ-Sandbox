import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge


BASE_DIR = Path(__file__).resolve().parent
SANDBOX_BINARY = BASE_DIR / "sandbox_api"
SANDBOX_TIMEOUT_SECONDS = 1.0
MAX_FEATURE_ABS = 1_000_000.0
MAX_OUTPUT_BYTES = 64 * 1024
MAX_LOG_LINES = 100

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024


def error_response(code, message, http_status, *, wall_ms=0.0,
                   return_code=None, logs=None):
    return jsonify({
        "status": "error",
        "error": {"code": code, "message": message},
        "execution": {
            "wall_ms": wall_ms,
            "return_code": return_code,
        },
        "sandbox_logs": logs or [],
    }), http_status


def validate_features(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")

    features = payload.get("features")
    if not isinstance(features, list) or len(features) != 3:
        raise ValueError("features 必须是恰好包含 3 个数值的数组")

    validated = []
    for value in features:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("features 中的每一项都必须是数值")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                f"features 的绝对值不能超过 {MAX_FEATURE_ABS:g}"
            ) from exc
        if not math.isfinite(number):
            raise ValueError("features 不能包含 NaN 或 Infinity")
        if abs(number) > MAX_FEATURE_ABS:
            raise ValueError(f"features 的绝对值不能超过 {MAX_FEATURE_ABS:g}")
        validated.append(number)

    return validated


def read_limited(output_file):
    output_file.flush()
    size = os.fstat(output_file.fileno()).st_size
    output_file.seek(0)
    data = output_file.read(MAX_OUTPUT_BYTES)
    return data.decode("utf-8", errors="replace"), size > MAX_OUTPUT_BYTES


def kill_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def parse_engine_output(stdout):
    result_candidates = []
    logs = []

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("{"):
            try:
                candidate = json.loads(line)
            except (json.JSONDecodeError, RecursionError) as exc:
                raise ValueError("沙盒输出的 JSON 无效或嵌套过深") from exc
            if isinstance(candidate, dict):
                result_candidates.append(candidate)
                continue
        if line:
            logs.append(line)

    if len(result_candidates) != 1:
        raise ValueError("沙盒必须输出且只能输出一个 JSON 结果")

    result = result_candidates[0]
    prediction = result.get("prediction")
    if result.get("status") != "success":
        raise ValueError("引擎没有返回 success 状态")
    if not isinstance(prediction, list) or len(prediction) != 2:
        raise ValueError("prediction 必须包含 2 个数值")
    for value in prediction:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("prediction 包含非法数值")
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, ValueError):
            finite = False
        if not finite:
            raise ValueError("prediction 包含非法数值")

    return result, logs


def collect_logs(stdout_logs, stderr):
    stderr_logs = [f"[stderr] {line}" for line in stderr.splitlines() if line]
    return (stdout_logs + stderr_logs)[-MAX_LOG_LINES:]


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_error):
    return error_response("REQUEST_TOO_LARGE", "请求体不能超过 4 KiB", 413)


@app.errorhandler(404)
def handle_not_found(_error):
    return error_response("NOT_FOUND", "接口不存在", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return error_response("METHOD_NOT_ALLOWED", "该接口不支持此 HTTP 方法", 405)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/v1/predict", methods=["POST"])
def predict():
    start_time = time.perf_counter()

    if not request.is_json:
        return error_response(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type 必须是 application/json",
            415,
        )

    payload = request.get_json(silent=True)
    try:
        features = validate_features(payload)
    except ValueError as exc:
        return error_response("INVALID_INPUT", str(exc), 400)

    input_data = (" ".join(format(value, ".17g") for value in features) + "\n").encode()

    try:
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                [str(SANDBOX_BINARY)],
                cwd=BASE_DIR,
                env={},
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                close_fds=True,
            )

            timed_out = False
            try:
                process.communicate(input=input_data, timeout=SANDBOX_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_process_group(process)

            stdout, stdout_exceeded = read_limited(stdout_file)
            stderr, stderr_exceeded = read_limited(stderr_file)
    except OSError as exc:
        wall_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return error_response(
            "SANDBOX_UNAVAILABLE",
            f"无法启动沙盒：{exc.strerror or exc}",
            503,
            wall_ms=wall_ms,
        )

    wall_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if timed_out:
        return error_response(
            "EXECUTION_TIMEOUT",
            f"执行超过 {SANDBOX_TIMEOUT_SECONDS:g} 秒，进程组已终止",
            504,
            wall_ms=wall_ms,
            return_code=process.returncode,
        )

    if stdout_exceeded or stderr_exceeded:
        return error_response(
            "OUTPUT_LIMIT_EXCEEDED",
            f"沙盒输出超过 {MAX_OUTPUT_BYTES // 1024} KiB",
            422,
            wall_ms=wall_ms,
            return_code=process.returncode,
        )

    provisional_logs = [line for line in stdout.splitlines() if line]
    logs = collect_logs(provisional_logs, stderr)

    if process.returncode == 128 + signal.SIGSYS:
        return error_response(
            "SANDBOX_VIOLATION",
            "引擎触发了未授权系统调用",
            422,
            wall_ms=wall_ms,
            return_code=process.returncode,
            logs=logs,
        )

    if process.returncode == 127:
        return error_response(
            "SANDBOX_START_FAILED",
            "Seccomp 初始化或引擎加载失败",
            503,
            wall_ms=wall_ms,
            return_code=process.returncode,
            logs=logs,
        )

    if process.returncode < 0:
        return error_response(
            "SANDBOX_CRASHED",
            f"沙盒被信号 {-process.returncode} 终止",
            502,
            wall_ms=wall_ms,
            return_code=process.returncode,
            logs=logs,
        )

    if process.returncode != 0:
        return error_response(
            "ENGINE_FAILED",
            f"引擎异常退出，错误码 {process.returncode}",
            422,
            wall_ms=wall_ms,
            return_code=process.returncode,
            logs=logs,
        )

    try:
        result, stdout_logs = parse_engine_output(stdout)
    except ValueError as exc:
        return error_response(
            "SANDBOX_PROTOCOL_ERROR",
            str(exc),
            502,
            wall_ms=wall_ms,
            return_code=process.returncode,
            logs=logs,
        )

    logs = collect_logs(stdout_logs, stderr)
    return jsonify({
        "status": "ok",
        "result": result,
        "execution": {
            "wall_ms": wall_ms,
            "return_code": process.returncode,
        },
        "sandbox_logs": logs,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8888)
