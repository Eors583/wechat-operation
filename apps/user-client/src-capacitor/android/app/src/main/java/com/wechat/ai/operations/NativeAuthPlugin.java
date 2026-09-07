package com.wechat.ai.operations;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

@CapacitorPlugin(name = "NativeAuth")
public class NativeAuthPlugin extends Plugin {
    private static final String KEY_ALIAS = "wechat-ai-refresh-token";
    private static final String PREFS = "wechat-ai-native-auth";
    private static final String TOKEN = "refresh-token";

    @PluginMethod
    public void loginSession(PluginCall call) {
        String identifier = call.getString("identifier");
        String password = call.getString("password");
        String deviceName = call.getString("deviceName");
        if (identifier == null || password == null || deviceName == null) {
            call.reject("Invalid native login request");
            return;
        }
        JSObject body = new JSObject();
        body.put("identifier", identifier);
        body.put("password", password);
        body.put("platform", "android");
        body.put("device_name", truncate(deviceName, 120));
        runRequest(call, "/auth/login", body, null, true);
    }

    @PluginMethod
    public void loginCodeSession(PluginCall call) {
        String identifier = call.getString("identifier");
        String verificationToken = call.getString("verificationToken");
        String deviceName = call.getString("deviceName");
        if (identifier == null || verificationToken == null || deviceName == null) {
            call.reject("Invalid native code-login request");
            return;
        }
        JSObject body = new JSObject();
        body.put("identifier", identifier);
        body.put("verification_token", verificationToken);
        body.put("platform", "android");
        body.put("device_name", truncate(deviceName, 120));
        runRequest(call, "/auth/login-code", body, null, true);
    }

    @PluginMethod
    public void refreshSession(PluginCall call) {
        try {
            String token = readToken();
            if (token == null) {
                resolveMissingToken(call);
                return;
            }
            JSONObject body = new JSONObject();
            body.put("refresh_token", token);
            runRequest(call, "/auth/refresh", body, null, true);
        } catch (Exception error) {
            call.reject("Native credential could not be read", error);
        }
    }

    @PluginMethod
    public void logoutSession(PluginCall call) {
        new Thread(() -> {
            try {
                String token = readToken();
                if (token == null) {
                    resolveMissingToken(call);
                    return;
                }
                JSONObject logoutBody = new JSONObject();
                logoutBody.put("refresh_token", token);
                AuthResponse response = performRequest("/auth/logout", logoutBody, call.getString("accessToken"), false);
                if (response.status == 401) {
                    JSONObject refreshBody = new JSONObject();
                    refreshBody.put("refresh_token", token);
                    AuthResponse refreshed = performRequest("/auth/refresh", refreshBody, null, true);
                    String accessToken = refreshed.payload.optString("access_token", "");
                    if (refreshed.status >= 200 && refreshed.status < 300 && !accessToken.isEmpty()) {
                        JSONObject retryBody = new JSONObject();
                        retryBody.put("refresh_token", readToken());
                        response = performRequest("/auth/logout", retryBody, accessToken, false);
                    } else {
                        response = refreshed;
                    }
                }
                resolveResponse(call, response);
            } catch (Exception error) {
                call.reject("Native logout request failed", error);
            }
        }, "wechat-ai-native-logout").start();
    }

    @PluginMethod
    public void clearRefreshToken(PluginCall call) {
        preferences().edit().remove(TOKEN).apply();
        call.resolve();
    }

    private void runRequest(PluginCall call, String path, JSONObject body, String accessToken, boolean rotateToken) {
        new Thread(() -> {
            try {
                resolveResponse(call, performRequest(path, body, accessToken, rotateToken));
            } catch (Exception error) {
                call.reject("Native authentication request failed", error);
            }
        }, "wechat-ai-native-auth").start();
    }

    private AuthResponse performRequest(String path, JSONObject body, String accessToken, boolean rotateToken) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) endpoint(path).openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(15_000);
            connection.setReadTimeout(30_000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Content-Type", "application/json");
            if (accessToken != null && !accessToken.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + accessToken);
            connection.setDoOutput(true);
            connection.getOutputStream().write(body.toString().getBytes(StandardCharsets.UTF_8));
            int status = connection.getResponseCode();
            InputStream stream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            JSONObject payload = readJson(stream);
            if (status >= 200 && status < 300 && rotateToken) {
                String refreshToken = payload.optString("refresh_token", "");
                if (refreshToken.isEmpty()) throw new IllegalStateException("Native auth response did not rotate the credential");
                storeToken(refreshToken);
                payload.remove("refresh_token");
            }
            return new AuthResponse(status, payload);
        } finally {
            connection.disconnect();
        }
    }

    private void resolveResponse(PluginCall call, AuthResponse response) {
        JSObject result = new JSObject();
        result.put("status", response.status);
        result.put("payload", response.payload);
        call.resolve(result);
    }

    private static final class AuthResponse {
        final int status;
        final JSONObject payload;

        AuthResponse(int status, JSONObject payload) {
            this.status = status;
            this.payload = payload;
        }
    }

    private URL endpoint(String path) throws Exception {
        URL base = new URL(BuildConfig.WECHAT_AI_API_BASE_URL);
        if (!"https".equals(base.getProtocol()) && !BuildConfig.DEBUG) throw new SecurityException("Native production authentication requires HTTPS");
        if (base.getUserInfo() != null || base.getRef() != null) throw new SecurityException("Invalid native API base URL");
        return new URL(BuildConfig.WECHAT_AI_API_BASE_URL.replaceAll("/$", "") + path);
    }

    private JSONObject readJson(InputStream stream) throws Exception {
        if (stream == null) return new JSONObject();
        StringBuilder content = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) content.append(line);
        }
        return content.length() == 0 ? new JSONObject() : new JSONObject(content.toString());
    }

    private SharedPreferences preferences() {
        return getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private SecretKey secretKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(KEY_ALIAS)) return ((KeyStore.SecretKeyEntry) keyStore.getEntry(KEY_ALIAS, null)).getSecretKey();
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build());
        return generator.generateKey();
    }

    private void storeToken(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, secretKey());
        byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        ByteBuffer buffer = ByteBuffer.allocate(4 + cipher.getIV().length + encrypted.length);
        buffer.putInt(cipher.getIV().length).put(cipher.getIV()).put(encrypted);
        preferences().edit().putString(TOKEN, Base64.encodeToString(buffer.array(), Base64.NO_WRAP)).apply();
    }

    private String readToken() throws Exception {
        String encoded = preferences().getString(TOKEN, null);
        if (encoded == null) return null;
        ByteBuffer buffer = ByteBuffer.wrap(Base64.decode(encoded, Base64.NO_WRAP));
        int ivLength = buffer.getInt();
        if (ivLength < 12 || ivLength > 16 || buffer.remaining() <= ivLength) throw new SecurityException("Invalid encrypted credential");
        byte[] iv = new byte[ivLength];
        byte[] encrypted = new byte[buffer.remaining() - ivLength];
        buffer.get(iv).get(encrypted);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), new GCMParameterSpec(128, iv));
        return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
    }

    private void resolveMissingToken(PluginCall call) {
        JSObject payload = new JSObject();
        payload.put("code", "REFRESH_TOKEN_REQUIRED");
        payload.put("message", "\u767b\u5f55\u51ed\u636e\u5df2\u5931\u6548\uff0c\u8bf7\u91cd\u65b0\u767b\u5f55\u3002");
        JSObject result = new JSObject();
        result.put("status", 401);
        result.put("payload", payload);
        call.resolve(result);
    }

    private String truncate(String value, int max) {
        return value.length() <= max ? value : value.substring(0, max);
    }
}
