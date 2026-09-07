import Capacitor
import Foundation
import Security

private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

@objc(NativeAuthPlugin)
final class NativeAuthPlugin: CAPPlugin, CAPBridgedPlugin {
    let identifier = "NativeAuthPlugin"
    let jsName = "NativeAuth"
    let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "loginSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "loginCodeSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "refreshSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "logoutSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearRefreshToken", returnType: CAPPluginReturnPromise),
    ]

    private let keychainService = "com.wechat.ai.operations.native-auth"
    private let keychainAccount = "refresh-token"

    @objc func loginSession(_ call: CAPPluginCall) {
        guard let identifier = call.getString("identifier"),
              let password = call.getString("password"),
              let deviceName = call.getString("deviceName") else {
            call.reject("Invalid native login request")
            return
        }
        request(call, path: "/auth/login", body: [
            "identifier": identifier,
            "password": password,
            "platform": "ios",
            "device_name": String(deviceName.prefix(120)),
        ], rotatesToken: true)
    }

    @objc func loginCodeSession(_ call: CAPPluginCall) {
        guard let identifier = call.getString("identifier"),
              let verificationToken = call.getString("verificationToken"),
              let deviceName = call.getString("deviceName") else {
            call.reject("Invalid native code-login request")
            return
        }
        request(call, path: "/auth/login-code", body: [
            "identifier": identifier,
            "verification_token": verificationToken,
            "platform": "ios",
            "device_name": String(deviceName.prefix(120)),
        ], rotatesToken: true)
    }

    @objc func refreshSession(_ call: CAPPluginCall) {
        guard let token = readToken() else {
            resolveMissingToken(call)
            return
        }
        request(call, path: "/auth/refresh", body: ["refresh_token": token], rotatesToken: true)
    }

    @objc func logoutSession(_ call: CAPPluginCall) {
        guard let token = readToken() else {
            resolveMissingToken(call)
            return
        }
        request(
            call,
            path: "/auth/logout",
            body: ["refresh_token": token],
            accessToken: call.getString("accessToken"),
            rotatesToken: false
        ) { [weak self] status, payload in
            guard let self else { return }
            guard status == 401, let currentToken = self.readToken() else {
                self.resolveResponse(call, status: status, payload: payload)
                return
            }
            self.request(call, path: "/auth/refresh", body: ["refresh_token": currentToken], rotatesToken: true) { [weak self] refreshStatus, refreshPayload in
                guard let self else { return }
                guard (200..<300).contains(refreshStatus),
                      let accessToken = refreshPayload["access_token"] as? String,
                      let rotatedToken = self.readToken() else {
                    self.resolveResponse(call, status: refreshStatus, payload: refreshPayload)
                    return
                }
                self.request(
                    call,
                    path: "/auth/logout",
                    body: ["refresh_token": rotatedToken],
                    accessToken: accessToken,
                    rotatesToken: false
                )
            }
        }
    }

    @objc func clearRefreshToken(_ call: CAPPluginCall) {
        SecItemDelete(keychainQuery() as CFDictionary)
        call.resolve()
    }

    private func request(
        _ call: CAPPluginCall,
        path: String,
        body: [String: Any],
        accessToken: String? = nil,
        rotatesToken: Bool,
        completion: ((Int, [String: Any]) -> Void)? = nil
    ) {
        let endpoint: URL
        do {
            endpoint = try authEndpoint(path: path)
        } catch {
            call.reject("Native API endpoint is invalid", nil, error)
            return
        }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let accessToken, !accessToken.isEmpty {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        } catch {
            call.reject("Native authentication body is invalid", nil, error)
            return
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        let delegate = NoRedirectDelegate()
        var session: URLSession?
        session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        session?.dataTask(with: request) { [weak self] data, response, error in
            defer { session?.finishTasksAndInvalidate() }
            guard let self else { return }
            if let error {
                call.reject("Native authentication request failed", nil, error)
                return
            }
            guard let response = response as? HTTPURLResponse else {
                call.reject("Native authentication response is invalid")
                return
            }
            let rawPayload = (data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]) ?? [:]
            var payload = rawPayload
            if (200..<300).contains(response.statusCode), rotatesToken {
                guard let refreshToken = payload["refresh_token"] as? String, !refreshToken.isEmpty else {
                    call.reject("Native auth response did not rotate the credential")
                    return
                }
                do {
                    try self.storeToken(refreshToken)
                } catch {
                    call.reject("Native credential could not be stored", nil, error)
                    return
                }
                payload.removeValue(forKey: "refresh_token")
            }
            if let completion {
                completion(response.statusCode, payload)
            } else {
                self.resolveResponse(call, status: response.statusCode, payload: payload)
            }
        }.resume()
    }

    private func resolveResponse(_ call: CAPPluginCall, status: Int, payload: [String: Any]) {
        call.resolve(["status": status, "payload": payload])
    }

    private func authEndpoint(path: String) throws -> URL {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "WechatAIApiBaseUrl") as? String,
              var components = URLComponents(string: value),
              components.user == nil,
              components.password == nil,
              components.fragment == nil else {
            throw URLError(.badURL)
        }
#if !DEBUG
        guard components.scheme == "https" else { throw URLError(.secureConnectionFailed) }
#else
        guard components.scheme == "https" || components.scheme == "http" else { throw URLError(.badURL) }
#endif
        components.path = components.path.replacingOccurrences(of: "/$", with: "", options: .regularExpression) + path
        guard let url = components.url else { throw URLError(.badURL) }
        return url
    }

    private func keychainQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
        ]
    }

    private func storeToken(_ token: String) throws {
        guard let data = token.data(using: .utf8) else { throw URLError(.cannotEncodeContentData) }
        SecItemDelete(keychainQuery() as CFDictionary)
        var query = keychainQuery()
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    private func readToken() -> String? {
        var query = keychainQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func resolveMissingToken(_ call: CAPPluginCall) {
        call.resolve([
            "status": 401,
            "payload": [
                "code": "REFRESH_TOKEN_REQUIRED",
                "message": "登录凭据已失效，请重新登录。",
            ],
        ])
    }
}
