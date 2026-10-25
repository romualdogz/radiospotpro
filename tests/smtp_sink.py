"""Minimaler SMTP-Server für Tests: nimmt Mails entgegen und speichert sie (ohne TLS)."""
from email import message_from_bytes, policy
import socketserver
import threading


class _Handler(socketserver.StreamRequestHandler):
    def _reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())

    def handle(self):
        sink = self.server.sink
        self._reply("220 test ESMTP")
        rcpt, data_mode, lines = [], False, []
        while raw := self.rfile.readline():
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if data_mode:
                if line == ".":
                    data_mode = False
                    sink.messages.append((rcpt, message_from_bytes(b"\r\n".join(lines), policy=policy.default)))
                    rcpt, lines = [], []
                    self._reply("250 OK")
                else:
                    lines.append(raw.rstrip(b"\r\n")[1:] if raw.startswith(b"..") else raw.rstrip(b"\r\n"))
                continue
            cmd = line.split(" ", 1)[0].upper()
            if cmd in ("EHLO", "HELO"):
                self._reply("250-test")
                self._reply("250 AUTH PLAIN LOGIN" if sink.auth else "250 SIZE 50000000")
            elif cmd == "AUTH":
                self._reply("235 OK" if sink.accept_auth else "535 Authentication failed")
            elif cmd == "RCPT":
                rcpt.append(line.split(":", 1)[1].strip(" <>"))
                self._reply("250 OK")
            elif cmd == "DATA":
                data_mode = True
                self._reply("354 go")
            elif cmd == "QUIT":
                self._reply("221 bye")
                return
            else:
                self._reply("250 OK")


class SmtpSink:
    def __init__(self, auth: bool = False, accept_auth: bool = True):
        self.messages: list = []
        self.auth, self.accept_auth = auth, accept_auth
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.sink = self  # type: ignore[attr-defined]
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
