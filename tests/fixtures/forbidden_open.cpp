#include <fcntl.h>
#include <unistd.h>

int main() {
    const int fd = open("/etc/passwd", O_RDONLY);
    if (fd >= 0) {
        close(fd);
    }
    return 0;
}
