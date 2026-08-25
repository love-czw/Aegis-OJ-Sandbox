#include <sys/socket.h>
#include <unistd.h>

int main() {
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd >= 0) {
        close(fd);
    }
    return 0;
}
