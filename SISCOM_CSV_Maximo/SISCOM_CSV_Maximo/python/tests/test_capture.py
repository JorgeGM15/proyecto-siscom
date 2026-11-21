import csv
import struct
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from siscom_core import FrameParser, SequenceClock, MotionAnalyzer, CSVRecorder, crc16_ccitt_false


def packet(seq, x=0, y=0, z=256):
    payload = struct.pack('<Hhhh', seq, x, y, z)
    crc = crc16_ccitt_false(payload)
    return b'\xAA\x55' + payload + struct.pack('<H', crc)


class CaptureTests(unittest.TestCase):
    def test_parser_fragmented_frame(self):
        parser = FrameParser()
        p = packet(5, -12, 34, -256)
        self.assertEqual(parser.feed(p[:3]), [])
        frames = parser.feed(p[3:])
        self.assertEqual(len(frames), 1)
        self.assertEqual((frames[0].sequence, frames[0].x, frames[0].y, frames[0].z), (5, -12, 34, -256))

    def test_sequence_clock_100hz(self):
        clock = SequenceClock(100)
        t0, _ = clock.timestamp(100, 1000.0)
        t1, lost = clock.timestamp(101, 1000.4)
        self.assertAlmostEqual(t1 - t0, .01, places=8)
        self.assertEqual(lost, 0)

    def test_sequence_clock_counts_missing(self):
        clock = SequenceClock(100)
        clock.timestamp(10, 1000.0)
        _, missing = clock.timestamp(13, 1000.2)
        self.assertEqual(missing, 2)
        self.assertEqual(clock.lost_packets, 2)

    def test_csv_writes_each_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'capture.csv'
            recorder = CSVRecorder(file, flush_every=2)
            clock = SequenceClock(100)
            analyzer = MotionAnalyzer()
            parser = FrameParser()
            for seq in range(5):
                for frame in parser.feed(packet(seq, seq, -seq, 256)):
                    ts, _ = clock.timestamp(frame.sequence, 100.0 + seq * .01)
                    recorder.add(analyzer.analyze(frame, ts, clock.lost_packets, 100))
            recorder.close()
            with file.open(newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 5)
            self.assertAlmostEqual(float(rows[-1]['t_rel_s']), .04, places=5)


if __name__ == '__main__':
    unittest.main()
