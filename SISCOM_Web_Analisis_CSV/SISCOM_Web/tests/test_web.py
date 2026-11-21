import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from fastapi.testclient import TestClient
import app as siscom_app


class WebDashboardTests(unittest.TestCase):
    def test_home_and_status(self):
        with TestClient(siscom_app.app) as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/api/status').status_code, 200)

    def test_demo_capture_download_and_analyze(self):
        filename = f'unit_test_{int(time.time())}.csv'
        with TestClient(siscom_app.app) as client:
            self.assertEqual(client.post('/api/demo/start').status_code, 200)
            time.sleep(0.12)
            start = client.post('/api/record/start', json={'filename': filename})
            self.assertEqual(start.status_code, 200, start.text)
            time.sleep(0.35)
            stop = client.post('/api/record/stop')
            self.assertEqual(stop.status_code, 200, stop.text)
            self.assertGreater(stop.json()['samples'], 10)
            download = client.get(stop.json()['download_url'])
            self.assertEqual(download.status_code, 200)
            self.assertGreater(len(download.text.splitlines()), 10)
            analysis = client.get('/api/analyze/' + filename)
            self.assertEqual(analysis.status_code, 200, analysis.text)
            self.assertEqual(set(analysis.json()['metrics']), {'X', 'Y', 'Z'})
            ts = analysis.json()['timeseries']
            self.assertEqual(ts['original_points'], analysis.json()['samples'])
            self.assertEqual(ts['time_pct'][0], 0)
            self.assertEqual(ts['time_pct'][-1], 100)
            self.assertEqual(len(ts['x_ms2']), len(ts['time_pct']))
            self.assertEqual(len(ts['y_ms2']), len(ts['time_pct']))
            self.assertEqual(len(ts['z_ms2']), len(ts['time_pct']))
            client.post('/api/disconnect')
        (ROOT / 'captures' / filename).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
