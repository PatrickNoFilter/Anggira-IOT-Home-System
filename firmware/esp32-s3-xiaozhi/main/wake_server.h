// ============================================================
//  wake_server.h — HTTP Server kecil di ESP32
//  Endpoint:
//    GET/POST /wake        — bangunkan Xiaozhi
//    POST     /say         — kirim teks perintah ke Xiaozhi AI
//    GET      /status      — cek status ESP32
//    GET      /response    — ambil respons terakhir Xiaozhi AI (tts)
//    GET      /stt         — ambil teks ucapan user terakhir (stt)
// ============================================================

#pragma once

#include <esp_http_server.h>
#include <esp_log.h>
#include <cJSON.h>
#include <functional>
#include <string>
#include <mutex>

#define WAKE_SERVER_TAG "WakeServer"
#define WAKE_SERVER_PORT 8080

class WakeServer {
public:
    static WakeServer& GetInstance() {
        static WakeServer instance;
        return instance;
    }

    WakeServer(const WakeServer&) = delete;
    WakeServer& operator=(const WakeServer&) = delete;

    void SetWakeCallback(std::function<void(const std::string&)> cb) {
        wake_callback_ = cb;
    }

    void SetSayCallback(std::function<void(const std::string&)> cb) {
        say_callback_ = cb;
    }

    // Dipanggil dari application.cc ketika Xiaozhi selesai bicara (tts sentence_start)
    void SetLastResponse(const std::string& text) {
        std::lock_guard<std::mutex> lock(response_mutex_);
        last_response_ = text;
        response_consumed_ = false;
        ESP_LOGI(WAKE_SERVER_TAG, "AI response stored: %s", text.c_str());
    }

    // Dipanggil dari application.cc ketika STT selesai (ucapan user)
    void SetLastStt(const std::string& text) {
        std::lock_guard<std::mutex> lock(response_mutex_);
        last_stt_ = text;
        ESP_LOGI(WAKE_SERVER_TAG, "STT stored: %s", text.c_str());
    }

    bool Start() {
        if (server_ != nullptr) {
            ESP_LOGW(WAKE_SERVER_TAG, "Server already running");
            return true;
        }

        httpd_config_t config = HTTPD_DEFAULT_CONFIG();
        config.server_port = WAKE_SERVER_PORT;
        config.lru_purge_enable = true;

        if (httpd_start(&server_, &config) != ESP_OK) {
            ESP_LOGE(WAKE_SERVER_TAG, "Failed to start HTTP server");
            return false;
        }

        // GET /wake
        httpd_uri_t wake_get = {
            .uri      = "/wake",
            .method   = HTTP_GET,
            .handler  = WakeGetHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &wake_get);

        // POST /wake
        httpd_uri_t wake_post = {
            .uri      = "/wake",
            .method   = HTTP_POST,
            .handler  = WakePostHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &wake_post);

        // POST /say
        httpd_uri_t say_post = {
            .uri      = "/say",
            .method   = HTTP_POST,
            .handler  = SayPostHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &say_post);

        // GET /status
        httpd_uri_t status_get = {
            .uri      = "/status",
            .method   = HTTP_GET,
            .handler  = StatusHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &status_get);

        // GET /response — ambil respons Xiaozhi AI terakhir
        httpd_uri_t response_get = {
            .uri      = "/response",
            .method   = HTTP_GET,
            .handler  = ResponseHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &response_get);

        // GET /stt — ambil teks ucapan user terakhir
        httpd_uri_t stt_get = {
            .uri      = "/stt",
            .method   = HTTP_GET,
            .handler  = SttHandler,
            .user_ctx = this
        };
        httpd_register_uri_handler(server_, &stt_get);

        ESP_LOGI(WAKE_SERVER_TAG, "HTTP Wake Server started on port %d", WAKE_SERVER_PORT);
        ESP_LOGI(WAKE_SERVER_TAG, "Endpoints:");
        ESP_LOGI(WAKE_SERVER_TAG, "  GET/POST http://192.168.1.10:%d/wake", WAKE_SERVER_PORT);
        ESP_LOGI(WAKE_SERVER_TAG, "  POST     http://192.168.1.10:%d/say", WAKE_SERVER_PORT);
        ESP_LOGI(WAKE_SERVER_TAG, "  GET      http://192.168.1.10:%d/status", WAKE_SERVER_PORT);
        ESP_LOGI(WAKE_SERVER_TAG, "  GET      http://192.168.1.10:%d/response", WAKE_SERVER_PORT);
        ESP_LOGI(WAKE_SERVER_TAG, "  GET      http://192.168.1.10:%d/stt", WAKE_SERVER_PORT);
        return true;
    }

    void Stop() {
        if (server_ != nullptr) {
            httpd_stop(server_);
            server_ = nullptr;
        }
    }

private:
    WakeServer() = default;
    ~WakeServer() { Stop(); }

    httpd_handle_t server_ = nullptr;
    std::function<void(const std::string&)> wake_callback_;
    std::function<void(const std::string&)> say_callback_;

    std::mutex  response_mutex_;
    std::string last_response_;     // teks respons Xiaozhi terakhir
    std::string last_stt_;          // teks ucapan user terakhir
    bool        response_consumed_ = true;  // sudah dibaca bot atau belum

    static esp_err_t SendJson(httpd_req_t *req, const char* json) {
        httpd_resp_set_type(req, "application/json");
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, json, strlen(json));
        return ESP_OK;
    }

    static std::string ReadBody(httpd_req_t *req) {
        char buf[256] = {0};
        int ret = httpd_req_recv(req, buf, sizeof(buf) - 1);
        if (ret > 0) {
            buf[ret] = '\0';
            return std::string(buf);
        }
        return "";
    }

    static esp_err_t WakeGetHandler(httpd_req_t *req) {
        auto* self = (WakeServer*)req->user_ctx;
        ESP_LOGI(WAKE_SERVER_TAG, "GET /wake");
        if (self->wake_callback_) self->wake_callback_("Hi ESP");
        return SendJson(req, "{\"status\":\"ok\",\"action\":\"wake\"}");
    }

    static esp_err_t WakePostHandler(httpd_req_t *req) {
        auto* self = (WakeServer*)req->user_ctx;
        std::string body = ReadBody(req);
        std::string wake_word = "Hi ESP";

        if (!body.empty()) {
            auto* json = cJSON_Parse(body.c_str());
            if (json) {
                auto* ww = cJSON_GetObjectItem(json, "wake_word");
                if (cJSON_IsString(ww)) wake_word = ww->valuestring;
                cJSON_Delete(json);
            }
        }

        ESP_LOGI(WAKE_SERVER_TAG, "POST /wake — wake_word: %s", wake_word.c_str());
        if (self->wake_callback_) self->wake_callback_(wake_word);
        return SendJson(req, "{\"status\":\"ok\",\"action\":\"wake\"}");
    }

    static esp_err_t SayPostHandler(httpd_req_t *req) {
        auto* self = (WakeServer*)req->user_ctx;
        std::string body = ReadBody(req);
        std::string text;

        if (!body.empty()) {
            auto* json = cJSON_Parse(body.c_str());
            if (json) {
                auto* t = cJSON_GetObjectItem(json, "text");
                if (cJSON_IsString(t)) text = t->valuestring;
                cJSON_Delete(json);
            }
        }

        if (text.empty()) {
            return SendJson(req, "{\"status\":\"error\",\"message\":\"text is required\"}");
        }

        ESP_LOGI(WAKE_SERVER_TAG, "POST /say — text: %s", text.c_str());
        if (self->say_callback_) self->say_callback_(text);
        return SendJson(req, "{\"status\":\"ok\",\"action\":\"say\"}");
    }

    static esp_err_t StatusHandler(httpd_req_t *req) {
        return SendJson(req,
            "{\"status\":\"ok\",\"device\":\"xiaozhi-esp32\","
            "\"mac\":\"3c:dc:75:6b:f9:ec\","
            "\"endpoints\":[\"/wake\",\"/say\",\"/status\",\"/response\",\"/stt\"]}");
    }

    // GET /response — kembalikan respons AI terakhir, tandai sudah dibaca
    static esp_err_t ResponseHandler(httpd_req_t *req) {
        auto* self = (WakeServer*)req->user_ctx;
        std::lock_guard<std::mutex> lock(self->response_mutex_);

        auto* root = cJSON_CreateObject();
        if (!self->last_response_.empty() && !self->response_consumed_) {
            cJSON_AddStringToObject(root, "status", "ok");
            cJSON_AddStringToObject(root, "text", self->last_response_.c_str());
            cJSON_AddTrueToObject(root, "new");
            self->response_consumed_ = true;
        } else if (!self->last_response_.empty()) {
            cJSON_AddStringToObject(root, "status", "ok");
            cJSON_AddStringToObject(root, "text", self->last_response_.c_str());
            cJSON_AddFalseToObject(root, "new");
        } else {
            cJSON_AddStringToObject(root, "status", "empty");
            cJSON_AddStringToObject(root, "text", "");
            cJSON_AddFalseToObject(root, "new");
        }

        char* json_str = cJSON_PrintUnformatted(root);
        cJSON_Delete(root);
        esp_err_t ret = SendJson(req, json_str);
        free(json_str);
        return ret;
    }

    // GET /stt — kembalikan teks ucapan user terakhir
    static esp_err_t SttHandler(httpd_req_t *req) {
        auto* self = (WakeServer*)req->user_ctx;
        std::lock_guard<std::mutex> lock(self->response_mutex_);

        auto* root = cJSON_CreateObject();
        cJSON_AddStringToObject(root, "status", "ok");
        cJSON_AddStringToObject(root, "text", self->last_stt_.c_str());

        char* json_str = cJSON_PrintUnformatted(root);
        cJSON_Delete(root);
        esp_err_t ret = SendJson(req, json_str);
        free(json_str);
        return ret;
    }
};
