#include <array>
#include <cstddef>
#include <unistd.h>

int main() {
    std::array<char, 8192> chunk{};

    for (int block = 0; block < 9; ++block) {
        std::size_t written = 0;
        while (written < chunk.size()) {
            const ssize_t result =
                write(STDOUT_FILENO, chunk.data() + written, chunk.size() - written);
            if (result <= 0) {
                return 1;
            }
            written += static_cast<std::size_t>(result);
        }
    }

    return 0;
}
