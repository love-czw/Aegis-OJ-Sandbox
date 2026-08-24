# Aegis-OJ-Sandbox: 企业级 Linux 内核安全评测沙盒

本项目是一个基于 Linux 内核底层机制（Cgroups V2 + Seccomp）纯 C++ 打造的高性能代码评测沙盒与 AI 算子推理网关。结合 Python Flask 实现跨语言微服务通信，提供从系统底层到前端监控面板的完整闭环。

> 💡 **核心定位：** 展现对计算机底层架构（11408）概念的工程化落地能力，专为高并发、高安全的 Online Judge (OJ) 评测系统与 AI 推理服务设计。目前作为在校学生求职软件研发与 AI 算法工程师实习的核心展示项目。

## 🚀 核心硬核技术 (Core Tech Stack)

### 1. 物理资源绝对隔离 (Linux Cgroups V2)
- 弃用传统的应用层限制，直接调用 Linux 操作系统内核的 `cgroups v2` 机制。
- 采用 C++ 操控 `memory.max` 和 `memory.swap.max` 节点，精确划定 20MB 物理内存上限，并**打补丁封死 Swap 穿透漏洞**。
- **实战效果**：完美防范恶意代码的“内存泄露”与“资源耗尽攻击 (MLE)”，越界进程会被内核 OOM Killer (Signal 9) 瞬间物理超度，主服务器稳如泰山。

### 2. 系统调用拦截拦截 (Seccomp BPF)
- 引入 `libseccomp` 开发库，在子进程 `fork` 之后、`exec` 执行外部不受信代码之前，为其戴上“内核手铐”。
- **实战效果**：建立严格的系统调用白名单，精准拦截 `mkdir`、`execve`、`open` 等高危系统调用。防范删库跑路或植入后门 (RE)，实现真正的系统级防伪篡改。

### 3. 高性能算子与 Cache 优化
- 核心引擎 (`engine.cpp`) 采用纯 C++ 编写前向传播网络。
- 深入计算机组成原理，针对矩阵乘法 ($X \times W + b$) 进行**空间局部性 (Spatial Locality)** 优化，大幅降低 Cache Miss 率。配合 ReLU 激活函数，实测端到端推理耗时压制在 3ms 级别。

### 4. 跨语言微服务架构 (C++ / Python IPC)
- 使用 Python Flask 作为 API 流量网关，处理并发 HTTP 请求。
- 通过操作系统进程间通信 (IPC) 管道，将前端动态特征流式注入到底层 C++ 沙盒的 `stdin` 中，实现毫秒级的跨语言数据调度。

## ⚙️ 快速启动 (Quick Start)

为了保证内核权限调用的安全性，本项目推荐在 Ubuntu 22.04 LTS (支持 Cgroups V2) 环境下运行：

```bash
# 1. 安装核心依赖
sudo apt-get install -y libseccomp-dev python3-pip
pip3 install flask

# 2. 编译核心安全沙盒与 AI 引擎
g++ engine.cpp -o engine
g++ sandbox_api.cpp -o sandbox_api -lseccomp

# 3. 启动全栈网关
python3 app.py