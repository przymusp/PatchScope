from collections import Counter

from gather_data import process_data, PurposeCounterResults, AnnotatedBugDataset


def test_AnnotatedBugDataset():
    dataset_path = 'test_dataset_annotated'
    annotated_bug_dataset = AnnotatedBugDataset(dataset_path)
    data = annotated_bug_dataset.gather_data(process_data, PurposeCounterResults.default)

    assert data._processed_files == [
        'test_dataset_annotated/CVE-2021-21332/annotation/e54746bdf7d5c831eabe4dcea76a7626f1de73df.json']
    assert data._hunk_purposes == Counter({'programming': 5, 'markup': 5, 'other': 2, 'documentation': 1})
    assert data._added_line_purposes == Counter({'programming': 45, 'documentation': 37, 'markup': 13, 'other': 1})
    assert data._removed_line_purposes == Counter({'programming': 25, 'markup': 13})
