# Aegis-OJ-Sandbox

Aegis 是一个面向学习与工程验证的受控执行原型：Flask 负责 HTTP 接口、输入校验与错误协议，C++ 启动器负责 `fork/exec`、进程状态回收与 Seccomp 过滤，固定的静态链接引擎负责演示标准输入/输出协议。

**技术栈：** C++17 · Linux · libseccomp · Python · Flask · pytest · Docker

> 当前版本只执行仓库内固定的 `./engine`，不接收用户源码或任意可执行文件。它不是完整 OJ，也不是可直接用于生产环境的通用不可信代码沙箱。

## 已实现能力

- `POST /api/v1/predict` JSON 接口，限制请求体为 4 KiB。
- 校验 `features` 必须为恰好 3 个有限数值，且绝对值不超过 `1,000,000`。
- 使用 `Popen(start_new_session=True)` 创建独立执行会话；执行超过 1 秒时通过进程组信号终止并回收子进程。
- 使用空环境启动沙盒进程，避免把 Flask 进程的环境变量传给固定引擎。
- 执行结束后按实际文件大小检测 stdout、stderr 是否超过 64 KiB，超限时拒绝结果；最多向客户端返回 100 行日志。
- 校验 C++ 引擎输出协议，将超时、非法系统调用、启动失败、异常退出和协议错误映射为稳定的 HTTP/JSON 错误。
- 在 C++ 子进程中设置 `PR_SET_NO_NEW_PRIVS`，并使用 `SCMP_ACT_KILL_PROCESS` 作为 Seccomp 默认策略。
- 对 stdin/stdout/stderr 的 `read/write` 设置文件描述符约束；Seccomp 规则创建或加载失败时拒绝执行引擎。
- 提供 pytest API 单元测试和 Ubuntu 22.04 Docker 集成测试。

## 执行链路

```text
HTTP Client
    |
    | POST /api/v1/predict
    v
Flask API: 请求校验、超时、输出上限、错误映射
    |
    | stdin: "1 -2 3\n"
    v
sandbox_api: fork -> PR_SET_NO_NEW_PRIVS -> Seccomp -> exec
    |
    v
固定静态引擎: stdout JSON
    |
    v
Flask: 协议校验 -> 结构化响应
```

`engine.cpp` 是一个 3 输入、2 输出的线性层加 ReLU 示例，只用于验证受控执行链路和输出协议，不代表完整 AI 推理服务。

## API 示例

请求：

```bash
curl -X POST http://127.0.0.1:8888/api/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"features":[1.0,-2.0,3.0]}'
```

成功响应结构：

```json
{
  "status": "ok",
  "result": {
    "status": "success",
    "prediction": [2.3, 0]
  },
  "execution": {
    "wall_ms": 1.23,
    "return_code": 0
  },
  "sandbox_logs": []
}
```

`wall_ms` 是每次请求的实际测量值，上面的数字只用于展示响应格式，不代表性能基准。

主要错误码：

| 错误码 | HTTP 状态 | 含义 |
| --- | ---: | --- |
| `INVALID_INPUT` | 400 | JSON 或特征值不符合接口约束 |
| `REQUEST_TOO_LARGE` | 413 | 请求体超过 4 KiB |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Content-Type 不是 JSON |
| `SANDBOX_VIOLATION` | 422 | 引擎触发未授权系统调用并收到 `SIGSYS` |
| `OUTPUT_LIMIT_EXCEEDED` | 422 | stdout 或 stderr 超过 64 KiB |
| `ENGINE_FAILED` | 422 | 引擎以非零状态退出 |
| `SANDBOX_CRASHED` | 502 | 沙盒进程被其他信号终止 |
| `EXECUTION_TIMEOUT` | 504 | 执行超过 1 秒，进程组已终止 |
| `SANDBOX_UNAVAILABLE` | 503 | 沙盒二进制无法启动 |
| `SANDBOX_START_FAILED` | 503 | Seccomp 初始化或引擎加载失败 |
| `SANDBOX_PROTOCOL_ERROR` | 502 | 引擎未返回唯一且合法的 JSON 结果 |

## 本地运行

推荐在 Ubuntu 22.04 上运行。需要 Python 3、C++17 编译器和 libseccomp 开发包：

```bash
sudo apt-get update
sudo apt-get install -y g++ libseccomp-dev python3 python3-venv

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
g++ -std=c++17 -O2 -static engine.cpp -o engine
g++ -std=c++17 -O2 sandbox_api.cpp -o sandbox_api -lseccomp
python app.py
```

服务默认只监听 `127.0.0.1:8888`，本机浏览器可打开 `http://127.0.0.1:8888` 进行演示。`app.py` 使用 Flask 开发服务器，只适合本地演示与测试。

## 测试

API 单元测试使用可控假进程验证输入、输出、错误码和进程控制契约，可在 macOS 或 Linux 上运行：

```bash
python3 -m pip install -r requirements-dev.txt
make test
```

在已经安装 `g++` 和 `libseccomp-dev` 的 Linux 环境运行真实集成测试：

```bash
make test-integration
```

Linux 集成测试会编译真实启动器、静态引擎与攻击探针，覆盖：

- 正常请求与预测结果；
- 文件读取和 socket 创建触发 `SIGSYS`；
- 死循环超时后无残留引擎进程；
- 输出洪泛以及通过回退文件偏移绕过检查的尝试被拒绝；
- 引擎缺失时失败关闭。

使用一次性 Ubuntu 22.04 容器运行完整测试：

```bash
make test-docker
```

容器运行时关闭网络，并仅关闭 Docker 外层默认 Seccomp，以便测试程序加载自己的更严格过滤器；测试不使用 `--privileged`。

## 安全边界

当前实现只面向仓库内固定的静态链接演示引擎。已有验证范围为 Ubuntu 22.04/ARM64；其他架构、libc、编译器或目标程序都需要重新跟踪系统调用并运行回归测试。

以下能力尚未实现：

- Cgroups v2 的内存、CPU 和 PID 配额；
- mount/PID/network/user namespace 隔离；
- 降权、capability 清理和只读文件系统；
- 按任务创建的独立工作目录与文件清理；
- 面向任意用户代码的编译、运行和判题流程；
- 生产级并发、性能基准与高可用部署。

Seccomp 只能按系统调用号和参数值过滤，不能按路径字符串限制 `execve`。当前启动链路为了加载固定引擎会放行 `execve`，因此不能把这套原型表述为“禁止任意程序执行”或“完整文件系统隔离”。

此外，64 KiB 输出限制是在进程输出写入临时文件后检查并拒绝，不是实时磁盘写入配额；1 秒超时由 Flask 网关执行，也不是内核级 CPU 配额。

## 项目结构

```text
app.py                              Flask API、进程控制和输出协议
sandbox_api.cpp                     C++ fork/exec 与 Seccomp 启动器
engine.cpp                          固定静态演示引擎
templates/index.html                简单演示页面
tests/test_app.py                   API 单元测试
tests/integration/test_linux_sandbox.py  Linux 集成测试
tests/fixtures/                     文件、socket、死循环和输出探针
Dockerfile.test                     Ubuntu 22.04 测试环境
```

## 后续计划

- [ ] 增加 Cgroups v2 资源限制与清理逻辑。
- [ ] 增加 namespace、降权和只读文件系统隔离。
- [ ] 在 x86_64 与 ARM64 环境持续运行集成测试。
- [ ] 完成威胁模型、性能基线和可复现实验记录。
- [ ] 在隔离边界完善后，再扩展为通用编译执行任务。
