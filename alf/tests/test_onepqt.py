import unittest
import tempfile
from pathlib import Path
import shutil

import pandas as pd
from pandas.testing import assert_frame_equal

import alf.onepqt as apt


class TestsONEParquet(unittest.TestCase):
    rel_ses_path = "mylab/Subjects/mysub/2021-02-28/001/"
    ses_info = {
        'lab': 'mylab',
        'subject': 'mysub',
        'date': '2021-02-28',
        'number': int('001'),
        'eid': 'mylab/Subjects/mysub/2021-02-28/001',
    }
    rel_ses_files = [Path('alf/spikes.times.npy')]

    def setUp(self) -> None:
        pd.set_option("display.max_columns", 12)

        # root path:
        self.tmpdir = Path(tempfile.gettempdir()) / 'pqttest'
        self.tmpdir.mkdir(exist_ok=True)
        # full session path:
        self.full_ses_path = self.tmpdir / self.rel_ses_path
        (self.full_ses_path / 'alf').mkdir(exist_ok=True, parents=True)

        self.file_path = self.full_ses_path / 'alf/spikes.times.npy'
        self.file_path.write_text('mock')

    def test_parse(self):
        self.assertEqual(apt._parse_rel_ses_path(self.rel_ses_path), self.ses_info)
        self.assertTrue(
            apt._get_full_ses_path(self.full_ses_path).endswith(self.rel_ses_path[:-1]))

    def test_walk(self):
        full_ses_paths = list(apt._find_sessions(self.tmpdir))
        self.assertTrue(len(full_ses_paths) >= 1)
        full_path = str(full_ses_paths[0])
        self.assertTrue(full_path.endswith(self.rel_ses_path[:-1]))
        rel_path = apt._get_file_rel_path(full_path)
        self.assertEqual(apt._parse_rel_ses_path(rel_path), self.ses_info)

    def test_walk_session(self):
        ses_files = list(apt._find_session_files(self.full_ses_path))
        self.assertEqual(ses_files, self.rel_ses_files)

    def test_parquet(self):
        # Test data
        columns = ('colA', 'colB')
        rows = [('a1', 'b1'), ('a2', 'b2')]
        metadata = apt._metadata('dbname')
        filename = self.tmpdir / 'mypqt.pqt'

        # Save parquet file.
        df = pd.DataFrame(rows, columns=columns)
        apt.df2pqt(filename, df, **metadata)

        # Load parquet file
        df2, metadata2 = apt.pqt2df(filename)
        assert_frame_equal(df, df2)
        self.assertTrue(metadata == metadata2)

    def test_sessions_df(self):
        df = apt._make_sessions_df(self.tmpdir)
        print("Sessions dataframe")
        print(df)
        self.assertEqual(df.loc[0].to_dict(), self.ses_info)

    def test_datasets_df(self):
        df = apt._make_datasets_df(self.tmpdir)
        print("Datasets dataframe")
        print(df)
        dset_info = df.loc[0].to_dict()
        self.assertEqual(dset_info['session_path'], str(self.rel_ses_path[:-1]))
        self.assertEqual(dset_info['rel_path'], str(self.rel_ses_files[0]))
        self.assertTrue(dset_info['file_size'] > 0)

    def tests_db(self):
        fn_ses, fn_dsets = apt.make_parquet_db(self.tmpdir)
        metadata_exp = apt._metadata(self.tmpdir)

        df_ses, metadata = apt.pqt2df(fn_ses)
        print(metadata)

        # Check sessions dataframe.
        self.assertEqual(metadata, metadata_exp)
        print(df_ses)
        self.assertEqual(df_ses.loc[0].to_dict(), self.ses_info)

        # Check datasets dataframe.
        df_dsets, metadata2 = apt.pqt2df(fn_dsets)
        self.assertEqual(metadata2, metadata_exp)
        print(df_dsets)
        dset_info = df_dsets.loc[0].to_dict()
        self.assertEqual(dset_info['session_path'], str(self.rel_ses_path[:-1]))
        self.assertEqual(dset_info['rel_path'], str(self.rel_ses_files[0]))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir)


if __name__ == "__main__":
    unittest.main(exit=False)
