#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cctype>
#include <csignal>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <limits>
#include <opencv2/opencv.hpp>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

#ifdef _WIN32
using socket_t = SOCKET;
constexpr socket_t INVALID_SOCKET_FD = INVALID_SOCKET;
#else
using socket_t = int;
constexpr socket_t INVALID_SOCKET_FD = -1;
#endif

bool initialize_network_stack() {
#ifdef _WIN32
    static bool initialized = false;
    if (initialized) {
        return true;
    }
    WSADATA wsa_data{};
    if (::WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
        return false;
    }
    initialized = true;
#endif
    return true;
}

void close_socket(socket_t fd) {
    if (fd == INVALID_SOCKET_FD) {
        return;
    }
#ifdef _WIN32
    ::closesocket(fd);
#else
    ::close(fd);
#endif
}

void shutdown_socket(socket_t fd) {
    if (fd == INVALID_SOCKET_FD) {
        return;
    }
#ifdef _WIN32
    ::shutdown(fd, SD_BOTH);
#else
    ::shutdown(fd, SHUT_RDWR);
#endif
}

struct Options {
    std::string render_mode = "beauty";
    std::string output_mode = "network";
    std::string camera = "/dev/video0";
    std::string output = "/dev/video43";
    std::string network_host = "0.0.0.0";
    int network_port = 8080;
    std::string network_path = "/mjpeg";
    int network_jpeg_quality = 70;
    std::string avatar;
    std::string avatar_dir;
    std::string avatar_name;
    bool gpio_avatar_select = false;
    int gpio0 = 0;
    int gpio1 = 1;
    double gpio_poll_interval = 0.20;
    std::string avatar_gpio_00 = "avatar_00";
    std::string avatar_gpio_01 = "avatar_01";
    std::string avatar_gpio_10 = "avatar_10";
    std::string avatar_gpio_11 = "avatar_11";
    int width = 960;
    int height = 540;
    int fps = 15;
    int detect_every = 2;
    double beauty_strength = 0.45;
    bool mirror = false;
    int max_faces = 1;
    double avatar_scale = 1.0;
    std::string eye_animation = "subtle";
    std::string mouth_animation = "normal";
    double mouth_y_offset = 0.0;
    double mouth_x_offset = 0.0;
    std::string background_mode = "camera";
    std::string fallback_style = "normal";
};

std::atomic<bool> g_stop_requested{false};

void handle_signal(int) {
    g_stop_requested.store(true);
}

std::string to_lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

std::string trim(std::string value) {
    auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), [&](unsigned char ch) { return !is_space(ch); }));
    value.erase(std::find_if(value.rbegin(), value.rend(), [&](unsigned char ch) { return !is_space(ch); }).base(), value.end());
    return value;
}

bool parse_int(const std::string& text, int& value) {
    try {
        size_t consumed = 0;
        const int parsed = std::stoi(text, &consumed, 10);
        if (consumed != text.size()) {
            return false;
        }
        value = parsed;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_double(const std::string& text, double& value) {
    try {
        size_t consumed = 0;
        const double parsed = std::stod(text, &consumed);
        if (consumed != text.size()) {
            return false;
        }
        value = parsed;
        return true;
    } catch (...) {
        return false;
    }
}

std::string get_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        return {};
    }
    ++index;
    return argv[index];
}

Options parse_args(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index];
        if (arg == "--render-mode") {
            options.render_mode = get_value(index, argc, argv);
        } else if (arg == "--output-mode") {
            options.output_mode = get_value(index, argc, argv);
        } else if (arg == "--camera") {
            options.camera = get_value(index, argc, argv);
        } else if (arg == "--output") {
            options.output = get_value(index, argc, argv);
        } else if (arg == "--network-host") {
            options.network_host = get_value(index, argc, argv);
        } else if (arg == "--network-port") {
            parse_int(get_value(index, argc, argv), options.network_port);
        } else if (arg == "--network-path") {
            options.network_path = get_value(index, argc, argv);
        } else if (arg == "--network-jpeg-quality") {
            parse_int(get_value(index, argc, argv), options.network_jpeg_quality);
        } else if (arg == "--avatar") {
            options.avatar = get_value(index, argc, argv);
        } else if (arg == "--avatar-dir") {
            options.avatar_dir = get_value(index, argc, argv);
        } else if (arg == "--avatar-name") {
            options.avatar_name = get_value(index, argc, argv);
        } else if (arg == "--gpio-avatar-select") {
            options.gpio_avatar_select = true;
        } else if (arg == "--gpio0") {
            parse_int(get_value(index, argc, argv), options.gpio0);
        } else if (arg == "--gpio1") {
            parse_int(get_value(index, argc, argv), options.gpio1);
        } else if (arg == "--gpio-poll-interval") {
            parse_double(get_value(index, argc, argv), options.gpio_poll_interval);
        } else if (arg == "--avatar-gpio-00") {
            options.avatar_gpio_00 = get_value(index, argc, argv);
        } else if (arg == "--avatar-gpio-01") {
            options.avatar_gpio_01 = get_value(index, argc, argv);
        } else if (arg == "--avatar-gpio-10") {
            options.avatar_gpio_10 = get_value(index, argc, argv);
        } else if (arg == "--avatar-gpio-11") {
            options.avatar_gpio_11 = get_value(index, argc, argv);
        } else if (arg == "--width") {
            parse_int(get_value(index, argc, argv), options.width);
        } else if (arg == "--height") {
            parse_int(get_value(index, argc, argv), options.height);
        } else if (arg == "--fps") {
            parse_int(get_value(index, argc, argv), options.fps);
        } else if (arg == "--detect-every") {
            parse_int(get_value(index, argc, argv), options.detect_every);
        } else if (arg == "--beauty-strength") {
            parse_double(get_value(index, argc, argv), options.beauty_strength);
        } else if (arg == "--mirror") {
            options.mirror = true;
        } else if (arg == "--max-faces") {
            parse_int(get_value(index, argc, argv), options.max_faces);
        } else if (arg == "--avatar-scale") {
            parse_double(get_value(index, argc, argv), options.avatar_scale);
        } else if (arg == "--eye-animation") {
            options.eye_animation = get_value(index, argc, argv);
        } else if (arg == "--mouth-animation") {
            options.mouth_animation = get_value(index, argc, argv);
        } else if (arg == "--mouth-y-offset") {
            parse_double(get_value(index, argc, argv), options.mouth_y_offset);
        } else if (arg == "--mouth-x-offset") {
            parse_double(get_value(index, argc, argv), options.mouth_x_offset);
        } else if (arg == "--background-mode") {
            options.background_mode = get_value(index, argc, argv);
        } else if (arg == "--fallback-style") {
            options.fallback_style = get_value(index, argc, argv);
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "avatar_gateway [options]\n";
            std::exit(0);
        }
    }
    options.output_mode = to_lower(options.output_mode);
    options.render_mode = to_lower(options.render_mode);
    options.background_mode = to_lower(options.background_mode);
    options.eye_animation = to_lower(options.eye_animation);
    options.mouth_animation = to_lower(options.mouth_animation);
    options.fallback_style = to_lower(options.fallback_style);
    options.network_path = options.network_path.empty() ? "/mjpeg" : options.network_path;
    options.width = std::max(1, options.width);
    options.height = std::max(1, options.height);
    options.fps = std::max(1, options.fps);
    options.detect_every = std::max(1, options.detect_every);
    options.max_faces = std::max(1, options.max_faces);
    options.network_jpeg_quality = std::clamp(options.network_jpeg_quality, 40, 95);
    options.avatar_scale = std::clamp(options.avatar_scale, 0.6, 3.0);
    options.beauty_strength = std::clamp(options.beauty_strength, 0.0, 1.0);
    return options;
}

std::string resolve_avatar_path(const Options& options) {
    const std::string selected_name = trim(options.avatar_name);
    const std::string avatar_path = trim(options.avatar);
    const std::string avatar_dir = trim(options.avatar_dir);

    std::vector<std::string> candidate_dirs;
    if (!avatar_dir.empty()) {
        candidate_dirs.push_back(avatar_dir);
    }
    if (!avatar_path.empty()) {
        candidate_dirs.push_back(fs::path(avatar_path).parent_path().string());
    }
    candidate_dirs.push_back((fs::path("assets") / "avatars").string());
    candidate_dirs.push_back("/opt/rk3588-avatar-gateway/assets/avatars");

    if (!selected_name.empty()) {
        std::vector<std::string> candidate_names{selected_name};
        if (selected_name.size() < 4 || to_lower(selected_name.substr(selected_name.size() - 4)) != ".png") {
            candidate_names.push_back(selected_name + ".png");
        }
        for (const auto& dir : candidate_dirs) {
            for (const auto& name : candidate_names) {
                const fs::path candidate = fs::path(dir) / name;
                if (fs::is_regular_file(candidate)) {
                    return candidate.string();
                }
            }
        }
    }

    if (!avatar_path.empty() && fs::is_regular_file(avatar_path)) {
        return avatar_path;
    }

    const std::vector<std::string> fallbacks = {
        (fs::path("assets") / "avatars" / "avatar_male.png").string(),
        (fs::path("assets") / "avatars" / "avatar_female.png").string(),
        (fs::path("assets") / "avatar.png").string(),
        "/opt/rk3588-avatar-gateway/assets/avatars/avatar_male.png",
        "/opt/rk3588-avatar-gateway/assets/avatar.png",
    };
    for (const auto& path : fallbacks) {
        if (fs::is_regular_file(path)) {
            return path;
        }
    }
    return {};
}

bool load_avatar(const std::string& path, cv::Mat& avatar) {
    if (path.empty() || !fs::is_regular_file(path)) {
        avatar.release();
        return false;
    }
    cv::Mat image = cv::imread(path, cv::IMREAD_UNCHANGED);
    if (image.empty()) {
        avatar.release();
        return false;
    }
    if (image.channels() == 3) {
        cv::cvtColor(image, avatar, cv::COLOR_BGR2BGRA);
        return true;
    }
    if (image.channels() == 4) {
        avatar = image;
        return true;
    }
    avatar.release();
    return false;
}

std::string find_cascade_file(const std::string& name) {
    const std::vector<std::string> roots = {
        "/usr/share/opencv4/haarcascades",
        "/usr/share/opencv/haarcascades",
        "/usr/local/share/opencv4/haarcascades",
    };
    for (const auto& root : roots) {
        const fs::path candidate = fs::path(root) / name;
        if (fs::is_regular_file(candidate)) {
            return candidate.string();
        }
    }
    return name;
}

cv::Mat make_stage_background(int width, int height) {
    cv::Mat background(height, width, CV_8UC3, cv::Scalar(14, 18, 28));
    for (int y = 0; y < height; ++y) {
        const double t = static_cast<double>(y) / std::max(1, height - 1);
        const cv::Vec3b row_color(
            static_cast<unsigned char>(20 + 12 * t),
            static_cast<unsigned char>(28 + 36 * t),
            static_cast<unsigned char>(46 + 72 * t));
        for (int x = 0; x < width; ++x) {
            background.at<cv::Vec3b>(y, x) = row_color;
        }
    }

    cv::rectangle(background, cv::Rect(0, 0, width, height), cv::Scalar(40, 60, 88), 2);
    cv::line(background, cv::Point(0, height / 8), cv::Point(width, height / 8), cv::Scalar(75, 120, 180), 1);
    cv::line(background, cv::Point(0, height * 7 / 8), cv::Point(width, height * 7 / 8), cv::Scalar(75, 120, 180), 1);
    cv::circle(background, cv::Point(width * 3 / 4, height / 4), std::max(20, std::min(width, height) / 8), cv::Scalar(90, 150, 210), 2);
    cv::putText(background, "RK3588 LIVE", cv::Point(width / 20, height - height / 12), cv::FONT_HERSHEY_SIMPLEX, 0.9, cv::Scalar(200, 220, 255), 2, cv::LINE_AA);
    return background;
}

cv::Mat apply_beauty(const cv::Mat& frame, double strength) {
    cv::Mat filtered;
    const int diameter = 5 + static_cast<int>(14.0 * strength);
    cv::bilateralFilter(frame, filtered, 0, std::max(5, diameter), std::max(5, diameter));
    cv::Mat result;
    const double filtered_weight = 0.35 + 0.45 * strength;
    cv::addWeighted(frame, 1.0 - filtered_weight, filtered, filtered_weight, 0.0, result);
    if (strength > 0.20) {
        cv::Mat sharp;
        cv::GaussianBlur(result, sharp, cv::Size(0, 0), 1.0);
        cv::addWeighted(result, 1.0 + 0.12 * strength, sharp, -0.12 * strength, 0.0, result);
    }
    return result;
}

cv::Rect grow_rect(const cv::Rect& rect, double scale, const cv::Size& bounds) {
    if (rect.width <= 0 || rect.height <= 0) {
        return {};
    }
    const double center_x = rect.x + rect.width / 2.0;
    const double center_y = rect.y + rect.height / 2.0;
    const double new_w = rect.width * scale;
    const double new_h = rect.height * scale;
    int x = static_cast<int>(center_x - new_w / 2.0);
    int y = static_cast<int>(center_y - new_h / 2.0);
    int w = static_cast<int>(new_w);
    int h = static_cast<int>(new_h);
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > bounds.width) {
        w = bounds.width - x;
    }
    if (y + h > bounds.height) {
        h = bounds.height - y;
    }
    if (w <= 0 || h <= 0) {
        return {};
    }
    return {x, y, w, h};
}

void alpha_blend_into(cv::Mat& background, const cv::Mat& foreground, const cv::Rect& target) {
    if (background.empty() || foreground.empty() || target.width <= 0 || target.height <= 0) {
        return;
    }
    const cv::Rect clipped = target & cv::Rect(0, 0, background.cols, background.rows);
    if (clipped.empty()) {
        return;
    }

    cv::Mat resized;
    cv::resize(foreground, resized, clipped.size(), 0, 0, cv::INTER_AREA);
    cv::Mat fg_bgra;
    if (resized.channels() == 3) {
        cv::cvtColor(resized, fg_bgra, cv::COLOR_BGR2BGRA);
    } else {
        fg_bgra = resized;
    }

    std::vector<cv::Mat> channels;
    cv::split(fg_bgra, channels);
    cv::Mat alpha = channels.size() == 4 ? channels[3] : cv::Mat(fg_bgra.rows, fg_bgra.cols, CV_8UC1, cv::Scalar(255));
    cv::Mat fg_bgr;
    if (channels.size() == 4) {
        std::vector<cv::Mat> bgr_channels{channels[0], channels[1], channels[2]};
        cv::merge(bgr_channels, fg_bgr);
    } else {
        fg_bgr = fg_bgra;
    }

    cv::Mat bg_roi = background(clipped);
    cv::Mat fg_float, bg_float, alpha_float;
    fg_bgr.convertTo(fg_float, CV_32FC3, 1.0 / 255.0);
    bg_roi.convertTo(bg_float, CV_32FC3, 1.0 / 255.0);
    alpha.convertTo(alpha_float, CV_32FC1, 1.0 / 255.0);
    cv::Mat alpha_3;
    cv::cvtColor(alpha_float, alpha_3, cv::COLOR_GRAY2BGR);
    cv::Mat result = fg_float.mul(alpha_3) + bg_float.mul(cv::Scalar::all(1.0) - alpha_3);
    result.convertTo(bg_roi, CV_8UC3, 255.0);
}

cv::Rect detect_face(const cv::Mat& frame, cv::CascadeClassifier& cascade) {
    if (cascade.empty()) {
        return {};
    }
    cv::Mat gray;
    cv::cvtColor(frame, gray, cv::COLOR_BGR2GRAY);
    cv::equalizeHist(gray, gray);
    std::vector<cv::Rect> faces;
    cascade.detectMultiScale(gray, faces, 1.1, 3, 0, cv::Size(48, 48));
    if (faces.empty()) {
        return {};
    }
    return *std::max_element(faces.begin(), faces.end(), [](const cv::Rect& a, const cv::Rect& b) {
        return a.area() < b.area();
    });
}

bool read_gpio_value(int pin, int& value) {
    const fs::path gpio_path = fs::path("/sys/class/gpio") / ("gpio" + std::to_string(pin)) / "value";
    std::ifstream file(gpio_path);
    if (!file.is_open()) {
        return false;
    }
    std::string text;
    std::getline(file, text);
    text = trim(text);
    if (text.empty()) {
        return false;
    }
    value = (text[0] == '1') ? 1 : 0;
    return true;
}

struct GpioAvatarSelector {
    bool enabled = false;
    int gpio0 = 0;
    int gpio1 = 1;
    double poll_interval = 0.20;
    std::string avatar_dir;
    std::string avatar_00;
    std::string avatar_01;
    std::string avatar_10;
    std::string avatar_11;
    std::chrono::steady_clock::time_point next_poll{std::chrono::steady_clock::now()};
    std::string current_name;

    std::string mapping_for_bits(int bits) const {
        switch (bits) {
            case 0: return avatar_00;
            case 1: return avatar_01;
            case 2: return avatar_10;
            case 3: return avatar_11;
            default: return avatar_00;
        }
    }

    std::string select(const std::string& current_path, cv::Mat& current_avatar) {
        if (!enabled) {
            return current_path;
        }
        const auto now = std::chrono::steady_clock::now();
        if (now < next_poll && !current_name.empty()) {
            return current_path;
        }
        next_poll = now + std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(poll_interval));

        int bit0 = 0;
        int bit1 = 0;
        if (!read_gpio_value(gpio0, bit0) || !read_gpio_value(gpio1, bit1)) {
            return current_path;
        }
        const int bits = (bit1 ? 2 : 0) | (bit0 ? 1 : 0);
        const std::string selected = mapping_for_bits(bits);
        if (selected.empty() || selected == current_name) {
            return current_path;
        }

        std::vector<std::string> search_dirs;
        if (!avatar_dir.empty()) {
            search_dirs.push_back(avatar_dir);
        }
        search_dirs.push_back((fs::path("assets") / "avatars").string());
        search_dirs.push_back("/opt/rk3588-avatar-gateway/assets/avatars");

        std::vector<std::string> candidate_names{selected};
        if (selected.size() < 4 || to_lower(selected.substr(selected.size() - 4)) != ".png") {
            candidate_names.push_back(selected + ".png");
        }

        for (const auto& dir : search_dirs) {
            for (const auto& candidate_name : candidate_names) {
                const fs::path candidate = fs::path(dir) / candidate_name;
                if (fs::is_regular_file(candidate)) {
                    cv::Mat loaded;
                    if (load_avatar(candidate.string(), loaded)) {
                        current_avatar = loaded;
                        current_name = selected;
                        return candidate.string();
                    }
                }
            }
        }
        return current_path;
    }
};

class MjpegServer {
public:
    MjpegServer(std::string host, int port, std::string path, int quality)
        : host_(std::move(host)), port_(port), path_(std::move(path)), quality_(quality) {}

    ~MjpegServer() {
        stop();
    }

    bool start() {
        if (running_) {
            return true;
        }

        if (!initialize_network_stack()) {
            std::cerr << "failed to initialize network stack" << '\n';
            return false;
        }

        listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
        if (listen_fd_ == INVALID_SOCKET_FD) {
            std::perror("socket");
            return false;
        }

        int reuse = 1;
        ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&reuse), sizeof(reuse));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(static_cast<uint16_t>(port_));
        if (host_ == "0.0.0.0") {
            addr.sin_addr.s_addr = INADDR_ANY;
        } else if (::inet_pton(AF_INET, host_.c_str(), &addr.sin_addr) != 1) {
            std::cerr << "invalid network host: " << host_ << '\n';
            close_socket(listen_fd_);
            listen_fd_ = INVALID_SOCKET_FD;
            return false;
        }

        if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
            std::perror("bind");
            close_socket(listen_fd_);
            listen_fd_ = INVALID_SOCKET_FD;
            return false;
        }

        if (::listen(listen_fd_, 8) < 0) {
            std::perror("listen");
            close_socket(listen_fd_);
            listen_fd_ = INVALID_SOCKET_FD;
            return false;
        }

        running_ = true;
        accept_thread_ = std::thread([this] { accept_loop(); });
        return true;
    }

    void stop() {
        if (!running_) {
            return;
        }
        running_ = false;
        cv_.notify_all();
        if (listen_fd_ != INVALID_SOCKET_FD) {
            shutdown_socket(listen_fd_);
            close_socket(listen_fd_);
            listen_fd_ = INVALID_SOCKET_FD;
        }
        if (accept_thread_.joinable()) {
            accept_thread_.join();
        }
    }

    void publish(const cv::Mat& frame) {
        std::vector<uchar> jpeg;
        std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, quality_};
        if (!cv::imencode(".jpg", frame, jpeg, params)) {
            return;
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            latest_jpeg_ = std::move(jpeg);
            ++version_;
        }
        cv_.notify_all();
    }

private:
    void accept_loop() {
        while (running_) {
            sockaddr_in client_addr{};
#ifdef _WIN32
            int client_len = sizeof(client_addr);
#else
            socklen_t client_len = sizeof(client_addr);
#endif
            const socket_t client_fd = ::accept(listen_fd_, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
            if (client_fd == INVALID_SOCKET_FD) {
                if (running_) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
                continue;
            }
            std::thread(&MjpegServer::client_loop, this, client_fd).detach();
        }
    }

    static bool send_all(socket_t fd, const void* data, size_t size) {
        const auto* bytes = static_cast<const std::uint8_t*>(data);
        size_t sent = 0;
        while (sent < size) {
#ifdef _WIN32
            const size_t remaining = size - sent;
            const int chunk_len = static_cast<int>(std::min<size_t>(remaining, static_cast<size_t>(std::numeric_limits<int>::max())));
            const int result = ::send(fd, reinterpret_cast<const char*>(bytes + sent), chunk_len, 0);
#else
            const ssize_t result = ::send(fd, bytes + sent, size - sent, 0);
#endif
            if (result <= 0) {
                return false;
            }
            sent += static_cast<size_t>(result);
        }
        return true;
    }

    void client_loop(socket_t client_fd) {
        const std::string boundary = "frame";
        const std::string header =
            "HTTP/1.0 200 OK\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-cache\r\n"
            "Pragma: no-cache\r\n"
            "Content-Type: multipart/x-mixed-replace; boundary=" + boundary + "\r\n\r\n";

        if (!send_all(client_fd, header.data(), header.size())) {
            close_socket(client_fd);
            return;
        }

        std::uint64_t local_version = 0;
        while (running_) {
            std::vector<uchar> jpeg;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                cv_.wait(lock, [&] { return !running_ || version_ != local_version; });
                if (!running_) {
                    break;
                }
                jpeg = latest_jpeg_;
                local_version = version_;
            }

            if (jpeg.empty()) {
                continue;
            }

            std::ostringstream part;
            part << "--" << boundary << "\r\n";
            part << "Content-Type: image/jpeg\r\n";
            part << "Content-Length: " << jpeg.size() << "\r\n\r\n";
            const std::string part_header = part.str();
            if (!send_all(client_fd, part_header.data(), part_header.size())) {
                break;
            }
            if (!send_all(client_fd, jpeg.data(), jpeg.size())) {
                break;
            }
            if (!send_all(client_fd, "\r\n", 2)) {
                break;
            }
        }

        shutdown_socket(client_fd);
        close_socket(client_fd);
    }

    std::string host_;
    int port_;
    std::string path_;
    int quality_;
    socket_t listen_fd_ = INVALID_SOCKET_FD;
    std::atomic<bool> running_{false};
    std::thread accept_thread_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::vector<uchar> latest_jpeg_;
    std::uint64_t version_ = 0;
};

bool open_camera(const std::string& device, const Options& options, cv::VideoCapture& capture) {
    const std::vector<std::string> candidates = {
        device,
        "/dev/video0",
        "/dev/video1",
        "/dev/video2",
        "/dev/video3",
    };
    for (const auto& candidate : candidates) {
        capture.open(candidate, cv::CAP_V4L2);
        if (capture.isOpened()) {
            capture.set(cv::CAP_PROP_FRAME_WIDTH, options.width);
            capture.set(cv::CAP_PROP_FRAME_HEIGHT, options.height);
            capture.set(cv::CAP_PROP_FPS, options.fps);
            return true;
        }
    }
    return false;
}

bool open_writer(const Options& options, cv::VideoWriter& writer) {
    const int fourcc = cv::VideoWriter::fourcc('M', 'J', 'P', 'G');
    if (options.output_mode == "usb") {
        writer.open(options.output, cv::CAP_V4L2, fourcc, options.fps, cv::Size(options.width, options.height), true);
        return writer.isOpened();
    }
    return false;
}

cv::Mat build_output_frame(const cv::Mat& frame,
                           const cv::Mat& avatar,
                           const std::string& render_mode,
                           const std::string& background_mode,
                           const cv::Rect& face_box,
                           double avatar_scale,
                           double beauty_strength) {
    const bool avatar_mode = render_mode == "avatar";
    const bool virtual_background = background_mode == "virtual";

    cv::Mat output = avatar_mode && virtual_background ? make_stage_background(frame.cols, frame.rows) : frame.clone();
    if (!avatar_mode) {
        output = apply_beauty(output, beauty_strength);
    }

    if (avatar_mode) {
        if (!avatar.empty() && !face_box.empty()) {
            const cv::Rect overlay_box = grow_rect(face_box, 1.35 * avatar_scale, output.size());
            alpha_blend_into(output, avatar, overlay_box);
        } else if (!virtual_background) {
            output = apply_beauty(output, beauty_strength * 0.6);
        }
    }
    return output;
}

}  // namespace

int main(int argc, char** argv) {
    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    const Options options = parse_args(argc, argv);

    cv::Mat avatar;
    const std::string avatar_path = resolve_avatar_path(options);
    if (!load_avatar(avatar_path, avatar)) {
        avatar.release();
    }

    GpioAvatarSelector gpio_selector;
    gpio_selector.enabled = options.gpio_avatar_select;
    gpio_selector.gpio0 = options.gpio0;
    gpio_selector.gpio1 = options.gpio1;
    gpio_selector.poll_interval = options.gpio_poll_interval;
    gpio_selector.avatar_dir = options.avatar_dir;
    gpio_selector.avatar_00 = options.avatar_gpio_00;
    gpio_selector.avatar_01 = options.avatar_gpio_01;
    gpio_selector.avatar_10 = options.avatar_gpio_10;
    gpio_selector.avatar_11 = options.avatar_gpio_11;

    cv::CascadeClassifier face_cascade;
    const std::string face_cascade_path = find_cascade_file("haarcascade_frontalface_default.xml");
    if (!face_cascade.load(face_cascade_path)) {
        std::cerr << "failed to load face cascade: " << face_cascade_path << '\n';
    }

    cv::VideoCapture capture;
    if (!open_camera(options.camera, options, capture)) {
        std::cerr << "failed to open camera: " << options.camera << '\n';
        return 1;
    }

    cv::VideoWriter writer;
    std::unique_ptr<MjpegServer> server;
    if (options.output_mode == "usb") {
        if (!open_writer(options, writer)) {
            std::cerr << "failed to open output device: " << options.output << '\n';
            return 1;
        }
    } else {
        server = std::make_unique<MjpegServer>(options.network_host, options.network_port, options.network_path, options.network_jpeg_quality);
        if (!server->start()) {
            std::cerr << "failed to start MJPEG server on " << options.network_host << ':' << options.network_port << '\n';
            return 1;
        }
    }

    std::cout << "camera=" << options.camera << '\n';
    std::cout << "render_mode=" << options.render_mode << '\n';
    std::cout << "output_mode=" << options.output_mode << '\n';
    std::cout << "output=" << options.output << '\n';
    std::cout << "output_size=" << options.width << 'x' << options.height << '\n';
    std::cout << "output_fps=" << options.fps << '\n';
    std::cout << "avatar_path=" << avatar_path << '\n';
    std::cout << "processing_started=true\n";
    std::cout.flush();

    const auto frame_delay = std::chrono::duration<double>(1.0 / std::max(1, options.fps));
    std::string current_avatar_path = avatar_path;
    cv::Mat current_avatar = avatar;
    cv::Rect last_face;
    int frame_index = 0;
    auto next_gpio_poll = std::chrono::steady_clock::now();

    while (!g_stop_requested.load()) {
        cv::Mat frame;
        if (!capture.read(frame) || frame.empty()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
            continue;
        }

        if (frame.size() != cv::Size(options.width, options.height)) {
            cv::resize(frame, frame, cv::Size(options.width, options.height), 0, 0, cv::INTER_AREA);
        }
        if (options.mirror) {
            cv::flip(frame, frame, 1);
        }

        const auto now = std::chrono::steady_clock::now();
        if (gpio_selector.enabled && now >= next_gpio_poll) {
            next_gpio_poll = now + std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(gpio_selector.poll_interval));
            const std::string next_path = gpio_selector.select(current_avatar_path, current_avatar);
            if (!next_path.empty()) {
                current_avatar_path = next_path;
            }
        }

        if (frame_index % options.detect_every == 0) {
            last_face = detect_face(frame, face_cascade);
        }
        ++frame_index;

        const cv::Mat output = build_output_frame(
            frame,
            current_avatar,
            options.render_mode,
            options.background_mode,
            last_face,
            options.avatar_scale,
            options.beauty_strength);

        if (options.output_mode == "usb") {
            writer.write(output);
        } else if (server) {
            server->publish(output);
        }

        std::this_thread::sleep_for(frame_delay * 0.15);
    }

    if (server) {
        server->stop();
    }
    writer.release();
    capture.release();
    return 0;
}