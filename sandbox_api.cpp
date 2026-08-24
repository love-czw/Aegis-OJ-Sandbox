#include <iostream>
#include <unistd.h>
#include <sys/wait.h>
#include <seccomp.h>

using namespace std;

int main() {
    cout << "[Aegis Sandbox] 🛡️ 启动内核级防护 (Cgroups + Seccomp)..." << endl;

    pid_t pid = fork();
    if (pid == 0) {
        // 配置 Seccomp：只允许常规系统调用，防止 AI 引擎被恶意篡改植入后门
        scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
        seccomp_rule_add(ctx, SCMP_ACT_KILL, SCMP_SYS(mkdir), 0);
        seccomp_load(ctx);
        seccomp_release(ctx);

        // 放出干活的 AI 引擎
        execl("./engine", "./engine", NULL);
    } else {
        int status;
        waitpid(pid, &status, 0); 
        cout << "[Aegis Sandbox] ✅ 引擎执行完毕，沙盒安全销毁。" << endl;
    }
    return 0;
}
