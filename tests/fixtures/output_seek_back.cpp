#include <array>
#include <cstddef>
#include <unistd.h>

namespace {

bool write_all(const char* data, std::size_t size) {
    std::size_t written = 0;
    while (written < size) {
        const ssize_t result =
            write(STDOUT_FILENO, data + written, size - written);
        if (result <= 0) {
            return false;
        }
        written += static_cast<std::size_t>(result);
    }
    return true;
}

}  // namespace

int main() {
    // Leave enough non-JSON space for the launcher to overwrite after the
    // engine seeks back. The valid result remains parseable by the old
    // offset-based limit check, while the file itself stays larger than 64 KiB.
    std::array<char, 4096> prefix{};
    prefix.fill('x');
    static constexpr char result[] =
        "\n{\"status\":\"success\",\"prediction\":[2.3,0]}\n";

    if (!write_all(prefix.data(), prefix.size()) ||
        !write_all(result, sizeof(result) - 1)) {
        return 1;
    }

    std::array<char, 8192> chunk{};
    chunk.fill('x');
    for (int block = 0; block < 9; ++block) {
        if (!write_all(chunk.data(), chunk.size())) {
            return 1;
        }
    }

    if (lseek(STDOUT_FILENO, 0, SEEK_SET) == -1) {
        return 1;
    }
    return 0;
}
