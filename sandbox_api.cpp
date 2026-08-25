#include <cerrno>
#include <csignal>
#include <iostream>
#include <seccomp.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>

using namespace std;

namespace {

int add_rule(scmp_filter_ctx ctx, int syscall) {
    return seccomp_rule_add(ctx, SCMP_ACT_ALLOW, syscall, 0);
}

int add_fd_rule(scmp_filter_ctx ctx, int syscall, int fd) {
    return seccomp_rule_add(
        ctx, SCMP_ACT_ALLOW, syscall, 1,
        SCMP_A0_32(SCMP_CMP_EQ, fd));
}

int setup_seccomp() {
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        return -1;
    }

    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_KILL_PROCESS);
    if (ctx == nullptr) {
        return -1;
    }

    int rc = 0;

    // The untrusted engine may only consume stdin and emit stdout/stderr.
    rc |= add_fd_rule(ctx, SCMP_SYS(read), STDIN_FILENO);
    rc |= add_fd_rule(ctx, SCMP_SYS(write), STDOUT_FILENO);
    rc |= add_fd_rule(ctx, SCMP_SYS(write), STDERR_FILENO);

    // The launch syscall is inherited by the static target. It cannot be
    // path-restricted by seccomp; filesystem isolation remains mandatory.
    rc |= add_rule(ctx, SCMP_SYS(execve));
    rc |= add_rule(ctx, SCMP_SYS(exit_group));
    rc |= add_rule(ctx, SCMP_SYS(exit));

    // Validated with strace for this statically linked engine on Ubuntu
    // 22.04/aarch64. Keep the profile under per-architecture regression tests.
    rc |= add_rule(ctx, SCMP_SYS(brk));
    rc |= add_rule(ctx, SCMP_SYS(mmap));
    rc |= add_rule(ctx, SCMP_SYS(munmap));
    rc |= add_rule(ctx, SCMP_SYS(mprotect));
    rc |= add_rule(ctx, SCMP_SYS(futex));
    rc |= add_rule(ctx, SCMP_SYS(getrandom));
    rc |= add_rule(ctx, SCMP_SYS(lseek));
    rc |= add_rule(ctx, SCMP_SYS(newfstatat));
    rc |= add_rule(ctx, SCMP_SYS(prlimit64));
    rc |= add_rule(ctx, SCMP_SYS(readlinkat));
    rc |= add_rule(ctx, SCMP_SYS(rseq));
    rc |= add_rule(ctx, SCMP_SYS(set_robust_list));
    rc |= add_rule(ctx, SCMP_SYS(set_tid_address));
    rc |= add_rule(ctx, SCMP_SYS(uname));
#if defined(__x86_64__)
    rc |= add_rule(ctx, SCMP_SYS(arch_prctl));
#endif

    if (rc != 0) {
        seccomp_release(ctx);
        return -1;
    }

    rc = seccomp_load(ctx);
    seccomp_release(ctx);
    return rc;
}

}  // namespace

int main() {
    cout << "[Aegis Sandbox] 🛡️ 启动 Strict Seccomp 白名单防护 (Static + Fail-Closed)..." << endl;

    const pid_t pid = fork();
    if (pid < 0) {
        cerr << "[Aegis-Parent] Fork 进程失败！" << endl;
        return 1;
    }

    if (pid == 0) {
        if (setup_seccomp() != 0) {
            static constexpr char err_msg[] =
                "[Aegis-Child] FATAL: Seccomp 初始化失败，拒绝执行引擎！\n";
            write(STDERR_FILENO, err_msg, sizeof(err_msg) - 1);
            _exit(127);
        }

        execl("./engine", "engine", nullptr);

        static constexpr char exec_err[] =
            "[Aegis-Child] FATAL: execl 加载引擎失败！\n";
        write(STDERR_FILENO, exec_err, sizeof(exec_err) - 1);
        _exit(127);
    }

    int status = 0;
    while (waitpid(pid, &status, 0) == -1) {
        if (errno != EINTR) {
            cerr << "[Aegis-Parent] waitpid 失败！" << endl;
            return 1;
        }
    }

    if (WIFEXITED(status)) {
        const int code = WEXITSTATUS(status);
        if (code == 0) {
            cout << "[Aegis-Parent] ✅ 引擎执行完毕，正常退出。" << endl;
            return 0;
        }
        cout << "[Aegis-Parent] ⚠️ 引擎异常退出，错误码: " << code << endl;
        return code;
    }

    if (WIFSIGNALED(status)) {
        const int sig = WTERMSIG(status);
        if (sig == SIGSYS) {
            cout << "[Aegis-Parent] 🚨 致命拦截：触发 Seccomp 白名单限制 (Bad Syscall)，进程已斩杀！" << endl;
        } else {
            cout << "[Aegis-Parent] 💥 进程被异常信号终止，信号值: " << sig << endl;
        }
        return 128 + sig;
    }

    cerr << "[Aegis-Parent] 无法识别子进程状态！" << endl;
    return 1;
}
