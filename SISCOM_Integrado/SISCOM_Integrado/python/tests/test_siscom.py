import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from siscom_core import (
    Frame, FrameParser, MotionAnalyzer, build_packet,
    crc16_ccitt_false, simulated_frame, simulation_bytes
)


class ProtocolTests(unittest.TestCase):
    def test_crc_known_standard(self):
        self.assertEqual(crc16_ccitt_false(b'123456789'), 0x29B1)

    def test_bytes_and_sign(self):
        parser = FrameParser()
        f = parser.feed(build_packet(65535, -122, 245, -300))
        self.assertEqual(f, [Frame(65535, -122, 245, -300)])

    def test_fragmentation(self):
        p = build_packet(100, 10, 20, 30)
        parser = FrameParser()
        self.assertEqual(parser.feed(p[:1]), [])
        self.assertEqual(parser.feed(p[1:9]), [])
        self.assertEqual(parser.feed(p[9:]), [Frame(100, 10, 20, 30)])

    def test_noise_bad_crc_and_resync(self):
        good = build_packet(2, 1, -1, 256)
        bad = bytearray(build_packet(1, 10, 10, 10))
        bad[7] ^= 0x40
        parser = FrameParser()
        result = parser.feed(b'garbage' + bad + good)
        self.assertEqual(result, [Frame(2, 1, -1, 256)])
        self.assertEqual(parser.crc_errors, 1)

    def test_lost_packets(self):
        analyzer = MotionAnalyzer()
        for i, seq in enumerate([0, 1, 4, 5]):
            analyzer.analyze(Frame(seq, 0, 0, 256), float(i)*.02)
        self.assertEqual(analyzer.lost_packets, 2)

    def test_mock_event(self):
        parser = FrameParser()
        analyzer = MotionAnalyzer()
        for i in range(400):
            for f in parser.feed(simulation_bytes(i)):
                analyzer.analyze(f, i / 50)
        self.assertEqual(parser.valid_frames, 400)
        self.assertGreater(analyzer.impact_events, 0)
        self.assertGreater(analyzer.vibration_events, 0)
        self.assertGreater(analyzer.tilt_events, 0)


if __name__ == '__main__':
    unittest.main()
