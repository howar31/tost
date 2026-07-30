// Minimal form-POST helper run from source (`swift token_post.swift <url> [headers...]`).
// Reads the request body from stdin; prints "<status>\n<response body>".
// Exists so token requests use Apple's TLS stack (URLSession) instead of
// Python's OpenSSL, whose handshake Tesla's auth edge rejects since 2026-07.
import Foundation

guard CommandLine.arguments.count >= 2,
      let url = URL(string: CommandLine.arguments[1]) else {
    FileHandle.standardError.write(Data("usage: swift token_post.swift <url> [\"Name: value\"...]\n".utf8))
    exit(2)
}

var request = URLRequest(url: url)
request.httpMethod = "POST"
for header in CommandLine.arguments.dropFirst(2) {
    if let colon = header.firstIndex(of: ":") {
        let name = String(header[..<colon]).trimmingCharacters(in: .whitespaces)
        let value = String(header[header.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
        request.setValue(value, forHTTPHeaderField: name)
    }
}
request.httpBody = FileHandle.standardInput.readDataToEndOfFile()

let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0
URLSession.shared.dataTask(with: request) { data, response, error in
    if let error = error {
        FileHandle.standardError.write(Data("request failed: \(error.localizedDescription)\n".utf8))
        exitCode = 1
    } else {
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        FileHandle.standardOutput.write(Data("\(status)\n".utf8))
        FileHandle.standardOutput.write(data ?? Data())
    }
    semaphore.signal()
}.resume()
semaphore.wait()
exit(exitCode)
