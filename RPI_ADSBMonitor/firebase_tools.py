def firebase_watcher(run): #Keep checking Firebase if run is true
    while True:
        prev_run_state = run
        current_run_state = check_run_status(run)
        
        if prev_run_state != current_run_state:
            if current_run_state:
                message_queue.put("Tracker activated - Starting data collection")
                print("Tracker activated via Firebase")
            else:
                message_queue.put("Tracker paused via Firebase")
                print("Tracker paused via Firebase")
        
        time.sleep(3) #Check every 3 seconds

def check_run_status(run):
    try:
        ref = db.reference("device_stats")
        data = ref.get()
        if data is not None and "run" in data:
            run = data["run"]
            if run:
                tracker_running_event.set()
            else:
                tracker_running_event.clear()
        else:
            ref.update({"run": run})
            if run:
                tracker_running_event.set()
            else:
                tracker_running_event.clear()
    except Exception as error:
        print(f"Firebase error checking run status: {error}")
    
    return run

def get_stats():
    today = datetime.today().strftime("%Y-%m-%d")
    csv_path = os.path.join('./stats_history', f'{today}.csv')

    default_stats = {
        'total': 0,
        'top_model': {'name': None, 'count': 0},
        'top_manufacturer': {'name': None, 'count': 0},
        'top_airline': {'name': None, 'count': 0},
        'manufacturer_breakdown': {},
        'last_updated': strftime("%H:%M:%S", localtime())
    }

    if not os.path.exists(csv_path):
        return default_stats

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            planes = []

            for row in reader:
                if not row.get('icao'):
                    continue

                manufacturer = row.get('manufacturer', '').strip()
                model = row.get('model', '').strip()
                airline = row.get('airline', '').strip()

                # Skip row if any key field is "-"
                if '-' in (manufacturer, model, airline):
                    continue

                planes.append({
                    'manufacturer': manufacturer,
                    'model': model,
                    'airline': airline
                })

            if not planes:
                return default_stats

            # Count occurrences
            model_counter = Counter(p['model'] for p in planes)
            manufacturer_counter = Counter(p['manufacturer'] for p in planes)
            airline_counter = Counter(p['airline'] for p in planes)

            top_model = model_counter.most_common(1)[0] if model_counter else (None, 0)
            top_manufacturer = manufacturer_counter.most_common(1)[0] if manufacturer_counter else (None, 0)
            top_airline = airline_counter.most_common(1)[0] if airline_counter else (None, 0)

            return {
                'total': len(planes),
                'top_model': {'name': top_model[0], 'count': top_model[1]},
                'top_manufacturer': {'name': top_manufacturer[0], 'count': top_manufacturer[1]},
                'top_airline': {'name': top_airline[0], 'count': top_airline[1]},
                'manufacturer_breakdown': dict(manufacturer_counter),
                'last_updated': strftime("%H:%M:%S", localtime())
            }

    except (FileNotFoundError, PermissionError, csv.Error, UnicodeDecodeError) as e:
        print(f"Error reading stats file: {e}")
        return default_stats
    except Exception as e:
        print(f"Unexpected error getting stats: {e}")
        return default_stats