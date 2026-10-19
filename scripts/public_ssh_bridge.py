"""Local SSH-to-TLS bridge for MobaXterm and Tailscale Funnel.

Run with the project non-base Python; connect MobaXterm to 127.0.0.1:2222.
TLS certificates and hostnames are verified. SSH authentication stays with sshd.
"""
import argparse
import select
import socket
import socketserver
import ssl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='xinmatrix.taila00da6.ts.net')
    parser.add_argument('--remote-port', type=int, default=8443)
    parser.add_argument('--local-port', type=int, default=2222)
    args = parser.parse_args()
    context = ssl.create_default_context()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                with socket.create_connection((args.host, args.remote_port), timeout=15) as raw:
                    with context.wrap_socket(raw, server_hostname=args.host) as remote:
                        remote.settimeout(None)
                        while True:
                            readable, _, _ = select.select([self.request, remote], [], [], 1)
                            if remote.pending() and remote not in readable:
                                readable.append(remote)
                            for source in readable:
                                data = source.recv(65536)
                                if not data:
                                    return
                                target = remote if source is self.request else self.request
                                target.sendall(data)
            except (OSError, ssl.SSLError) as exc:
                print(f'Connection failed: {exc}', flush=True)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with Server(('127.0.0.1', args.local_port), Handler) as server:
        print(f'MobaXterm: host 127.0.0.1, port {args.local_port}, user michelle', flush=True)
        print(f'TLS destination: {args.host}:{args.remote_port}; Ctrl+C to stop', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
