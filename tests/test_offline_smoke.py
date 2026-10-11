"""Offline validation without requesting any NEON data or API credentials."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
import numpy as np
import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'neon_fish_oxygen_pilot.py'


def load_functions():
    source = SCRIPT.read_text(encoding='utf-8')
    ast.parse(source)  # Syntax check: the full script.
    tree = ast.parse(source)
    wanted = {'metadata_from_neon_filename', 'metrics_from_hourly'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    if len(nodes) != 2:
        raise AssertionError('Expected two named pipeline functions.')
    scope = {
        'Path': Path, 'pd': pd, 'np': np, 'MIN_COVERAGE': 0.7,
        'DO_CUTOFF': 5.0,
        'SENSOR_FILE_PATTERN': re.compile(
            r'^NEON\.D\d{2}\.(?P<site>[A-Z0-9]{4})\.'
            r'DP1\.20288\.001\.'
            r'(?P<hor>[A-Z0-9]{3})\.'
            r'(?P<ver>[A-Z0-9]{3})\.'
            r'(?P<tmi>[A-Z0-9]{3})\.'
            r'waq_instantaneous\.', re.IGNORECASE
        ),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), 'exec'), scope)
    return scope


class OfflinePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fn = load_functions()

    def test_sensor_file_metadata(self):
        name = ('NEON.D04.GUIL.DP1.20288.001.101.100.100.'
                'waq_instantaneous.2023-10.basic.20251209T034224Z.csv')
        meta = self.fn['metadata_from_neon_filename'](name)
        self.assertEqual(meta['siteID'], 'GUIL')
        self.assertEqual(meta['horizontalPosition'], '101')
        self.assertEqual(meta['verticalPosition'], '100')
        self.assertEqual(meta['temporalIndex'], '100')
        self.assertIsNone(self.fn['metadata_from_neon_filename']('renamed.csv'))

    def test_complete_constant_oxygen_window(self):
        end = pd.Timestamp('2023-11-01', tz='UTC')
        idx = pd.date_range(end-pd.Timedelta(days=7), periods=7*24, freq='h')
        s = pd.Series(np.full(len(idx), 8.5), index=idx)
        result = self.fn['metrics_from_hourly'](s, end, 7)
        self.assertEqual(result['hours_good'], 168)
        self.assertAlmostEqual(result['coverage'], 1.0)
        self.assertAlmostEqual(result['do_mean'], 8.5)
        self.assertAlmostEqual(result['prop_below_5'], 0.0)

    def test_sparse_window_is_not_reported_as_valid(self):
        end = pd.Timestamp('2023-11-01', tz='UTC')
        idx = pd.date_range(end-pd.Timedelta(days=7), periods=24, freq='h')
        s = pd.Series(np.full(len(idx), 4.5), index=idx)
        result = self.fn['metrics_from_hourly'](s, end, 7)
        self.assertTrue(np.isnan(result['do_mean']))
        self.assertAlmostEqual(result['coverage'], 24/168)


if __name__ == '__main__':
    unittest.main()
