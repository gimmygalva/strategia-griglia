use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::time::Duration;

pub fn port_from_url(url: &str) -> Result<u16, String> {
    let value = url
        .strip_prefix("http://127.0.0.1:")
        .ok_or_else(|| "Backend must bind IPv4 loopback".to_string())?;
    if value.is_empty() || !value.bytes().all(|value| value.is_ascii_digit()) {
        return Err("Invalid local backend port".to_string());
    }
    let port: u16 = value.parse().map_err(|_| "Invalid local backend port")?;
    if port == 0 {
        return Err("Backend port is not ready".to_string());
    }
    Ok(port)
}

pub fn request(url: &str, token: &str, method: &str, path: &str) -> Result<Vec<u8>, String> {
    let port = port_from_url(url)?;
    if !matches!(method, "GET" | "POST") || !path.starts_with("/api/") {
        return Err("Unsupported desktop request".to_string());
    }
    if token.len() != 64 || !token.bytes().all(|value| value.is_ascii_hexdigit()) {
        return Err("Invalid desktop session token".to_string());
    }
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(3))
        .map_err(|_| "Local backend connection failed".to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| "Cannot configure backend timeout".to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| "Cannot configure backend timeout".to_string())?;
    let body = if method == "POST" { "{}" } else { "" };
    let message = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream
        .write_all(message.as_bytes())
        .map_err(|_| "Local backend request failed".to_string())?;
    let mut response = Vec::new();
    stream
        .take(1_048_576)
        .read_to_end(&mut response)
        .map_err(|_| "Local backend response failed".to_string())?;
    let header_end = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "Invalid local HTTP response".to_string())?;
    let headers = std::str::from_utf8(&response[..header_end])
        .map_err(|_| "Invalid local HTTP headers".to_string())?;
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1));
    if status != Some("200") {
        return Err("Local backend rejected the request".to_string());
    }
    Ok(response[header_end + 4..].to_vec())
}

pub fn health(url: &str, token: &str) -> Result<(), String> {
    let response = request(url, token, "GET", "/api/health")?;
    let body: serde_json::Value = serde_json::from_slice(&response)
        .map_err(|_| "Backend health response is invalid".to_string())?;
    if body.get("status").and_then(|value| value.as_str()) != Some("ok") {
        return Err("Backend is not healthy".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_explicit_loopback_is_accepted() {
        assert_eq!(port_from_url("http://127.0.0.1:43567").unwrap(), 43567);
        for invalid in [
            "https://127.0.0.1:80",
            "http://localhost:80",
            "http://0.0.0.0:80",
            "http://api.bybit.com:80",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:80/path",
            "http://127.0.0.1:80\r\nInjected: yes",
        ] {
            assert!(port_from_url(invalid).is_err(), "accepted {invalid}");
        }
    }

    #[test]
    fn tokens_cannot_inject_headers() {
        assert!(request("http://127.0.0.1:80", "bad\r\nX: y", "GET", "/api/health").is_err());
    }
}
