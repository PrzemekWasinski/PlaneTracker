def restart_script(): #Function to restart the script
    print("Restarting script")
    time.sleep(2)
    os.execv(sys.executable, ["python3"] + sys.argv)

def connect(server): #Connects to ADSB receiver
    while True:
        try:
            sock = socket.create_connection(server)
            print(f"Connected to {server}")
            return sock
        except Exception as error:
            print(f"Failed to connect: {error}. Attempting to reconnect")
            time.sleep(3)