import csv
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'analizar_movimiento.py'
spec = importlib.util.spec_from_file_location('analyzer', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class AnalyzerTests(unittest.TestCase):
    def test_axis_x_is_strongest(self):
        rows=[]
        for i in range(501):
            t=i/50
            # Z gravity; dynamic oscillation only on X.
            x=0.25*math.sin(2*math.pi*2*t)
            rows.append((t,x,0.0,1.0))
        r=mod.analyze(rows)
        self.assertEqual(r['strongest'],'X')
        self.assertGreater(r['metrics']['X']['rms_g'],r['metrics']['Y']['rms_g'])

    def test_static_gravity_not_called_movement(self):
        rows=[(i/50,0.0,0.0,1.0) for i in range(101)]
        r=mod.analyze(rows)
        self.assertLess(r['metrics']['Z']['rms_g'],0.001)

    def test_load_siscom_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'sample.csv'
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['t_rel_s','ax_g','ay_g','az_g'])
                w.writeheader()
                w.writerow({'t_rel_s':0,'ax_g':0,'ay_g':0,'az_g':1})
                w.writerow({'t_rel_s':0.02,'ax_g':0.1,'ay_g':0,'az_g':1})
            rows=mod.load_samples(p)
            self.assertEqual(len(rows),2)

if __name__=='__main__':
    unittest.main()
