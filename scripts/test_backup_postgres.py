import unittest

from scripts.backup_postgres import normalize_columns


def column(name, position, table='example', data_type='integer'):
    return (table, name, data_type, data_type, 'NO', None, position, 'NO', None)


class ColumnComparisonTests(unittest.TestCase):
    def test_dropped_column_gaps_are_ignored(self):
        self.assertEqual(
            normalize_columns([column('id', 1), column('app_label', 3), column('model', 4)]),
            normalize_columns([column('id', 1), column('app_label', 2), column('model', 3)]),
        )

    def test_real_changes_are_not_ignored(self):
        original = normalize_columns([column('id', 1), column('label', 3)])
        for changed in (
            [column('label', 1), column('id', 2)],
            [column('id', 1)],
            [column('id', 1), column('renamed', 2)],
            [column('id', 1), column('label', 2, data_type='text')],
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(original, normalize_columns(changed))

    def test_positions_restart_for_each_table(self):
        result = normalize_columns([column('id', 3, 'a'), column('id', 4, 'b')])
        self.assertEqual([row[6] for row in result], [1, 1])


if __name__ == '__main__':
    unittest.main()
