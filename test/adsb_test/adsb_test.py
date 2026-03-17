import socket

HOST = "localhost"
PORT = 30003


def main():
    print(f"Connecting to {HOST}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    sock.settimeout(1.0)
    buffer = ""

    print("Connected. Printing raw messages. Press Ctrl+C to stop.\n")

    try:
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    print("Connection closed by server")
                    break

                buffer += data.decode(errors="ignore")
                lines = buffer.split("\n")
                buffer = lines.pop() if lines else ""

                for line in lines:
                    line = line.strip()
                    if line:
                        print(line)
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
