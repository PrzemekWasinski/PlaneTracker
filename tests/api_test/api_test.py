import json
import os
import requests
import time
from datetime import datetime

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'api_test_output.txt')

# ICAOs from the readsb test output
TEST_ICAOS = ['407cb2', '40643b', '40753c', 'ac3c0e', '40095d', '4cae8d', '06a13a', 'aaa6e4']


def test_hexdb(icao):
    url = f'https://hexdb.io/api/v1/aircraft/{icao}'
    try:
        t0 = time.time()
        response = requests.get(url, timeout=10)
        elapsed = time.time() - t0
        return {
            'url': url,
            'status': response.status_code,
            'elapsed_ms': round(elapsed * 1000),
            'body': response.json() if response.status_code == 200 else response.text[:300],
        }
    except Exception as e:
        return {'url': url, 'error': f'{type(e).__name__}: {e}'}


def test_opensky(icao):
    url = f'https://opensky-network.org/api/metadata/aircraft/icao/{icao}'
    try:
        t0 = time.time()
        response = requests.get(url, timeout=10)
        elapsed = time.time() - t0
        return {
            'url': url,
            'status': response.status_code,
            'elapsed_ms': round(elapsed * 1000),
            'body': response.json() if response.status_code == 200 else response.text[:300],
        }
    except Exception as e:
        return {'url': url, 'error': f'{type(e).__name__}: {e}'}


def run():
    lines = []
    lines.append(f'API test — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('')

    for icao in TEST_ICAOS:
        lines.append('=' * 60)
        lines.append(f'ICAO: {icao.upper()}')
        lines.append('=' * 60)

        lines.append('\n--- hexdb.io ---')
        result = test_hexdb(icao)
        if 'error' in result:
            lines.append(f'  ERROR: {result["error"]}')
        else:
            lines.append(f'  Status: {result["status"]}  ({result["elapsed_ms"]}ms)')
            lines.append(f'  Response: {json.dumps(result["body"], indent=4)}')

        lines.append('\n--- OpenSky ---')
        result = test_opensky(icao)
        if 'error' in result:
            lines.append(f'  ERROR: {result["error"]}')
        else:
            lines.append(f'  Status: {result["status"]}  ({result["elapsed_ms"]}ms)')
            lines.append(f'  Response: {json.dumps(result["body"], indent=4)}')

        lines.append('')

    output = '\n'.join(lines)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f'Written to {OUTPUT_FILE}')


if __name__ == '__main__':
    run()
