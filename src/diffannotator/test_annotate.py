import copy
from pathlib import Path
from pprint import pprint
from textwrap import dedent

from pygments.lexers import CLexer
import pytest
import unidiff

from new_annotate import (split_multiline_lex_tokens, line_ends_idx,
                          group_tokens_by_line, front_fill_gaps, deep_update,
                          clean_text, line_is_comment, annotate_single_diff,
                          Bug, BugDataset)


# Example code to be tokenized
example_C_code = r'''
 /**
  * brief       Calculate approximate memory requirements for raw encoder
  *
  */
  int i = 1; /* an int */
'''


def test_line_ends_idx():
    text = "1st line\n2nd line\n3rd then empty\n\n5th line\n"
    pos_list = line_ends_idx(text)

    assert "1st line\n" == text[0:pos_list[0]]
    assert "2nd line\n" == text[pos_list[0]:pos_list[1]]


def test_front_fill_gaps():
    input_data = {1: '1',
                  4: '4',
                  5: '5',
                  7: '7'}
    expected = {1: '1', 2: '1', 3: '1',
                4: '4',
                5: '5', 6: '5',
                7: '7'}

    actual = front_fill_gaps(input_data)

    assert actual == expected


def test_deep_update():
    original = {
        "level1": {
            "level2": {"level3-A": 0, "level3-B": 1}
        },
        "list": list('abc'),
    }
    dictionary = copy.deepcopy(original)
    update = {
        "level1": {
            "level2": {"level3-B": 10}
        },
        "list": list('de'),
        "new key": 1,
    }
    result = deep_update(dictionary, update)

    # check a few cases
    assert result["level1"]["level2"]["level3-A"] == 0, \
        "deeply nested 'level3-A' value kept"
    assert result["level1"]["level2"]["level3-B"] == 10, \
        "deeply nested 'level3-B' value updated"
    assert result["list"] == list('abcde'), \
        "list value 'list' extended"
    assert "new key" in result and result["new key"] == 1, \
        "new key 'new key' added"


def test_clean_text():
    input = "some text with * / \\ \t and\nnew\nlines     and  spaces"
    expected = "some text with andnewlines and spaces"
    actual = clean_text(input)

    assert actual == expected


def test_post_image_from_diff():
    file_path = 'test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'
    patch = unidiff.PatchSet.from_filename(file_path, encoding='utf-8')
    assert len(patch) == 1, "there is only one changed file in patch set"
    hunk = patch[0][0]

    line_type = unidiff.LINE_TYPE_ADDED
    source = ''.join([str(line.value) for line in hunk
                      # unexpectedly, there is no need to check for unidiff.LINE_TYPE_EMPTY
                      if line.line_type in {line_type, unidiff.LINE_TYPE_CONTEXT}])

    # end first line with \ to avoid the empty line
    expected = dedent("""\
            if isinstance(iterable, np.ndarray):
                return tqdm_class(np.ndenumerate(iterable),
                                  total=total or len(iterable), **tqdm_kwargs)
        return enumerate(tqdm_class(iterable, **tqdm_kwargs), start)
    
    
    def _tzip(iter1, *iter2plus, **tqdm_kwargs):""")

    assert source == expected, "post image matches expected result"


def test_annotate_single_diff():
    # code patch
    file_path = 'test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'
    patch = annotate_single_diff(file_path)
    # check file data
    expected_language_data = {
        'language': 'Python',
        'purpose': 'programming',
        'type': 'programming',
    }
    changed_file_name = 'tqdm/contrib/__init__.py'
    assert changed_file_name in patch, \
        "correct file name is used in patch data"
    assert expected_language_data.items() <= patch[changed_file_name].items(), \
        "correct language is being detected"
    # check line data
    # - check number of`changes
    assert len(patch[changed_file_name]['-']) == 1, \
        "there is only one removed line (one changed line)"
    assert len(patch[changed_file_name]['+']) == 1, \
        "there is only one added line (one changed line)"
    # - check content of changes
    actual_removed = ''.join([x[2]  # value, that is, text_fragment
                              for x in patch[changed_file_name]['-'][0]['tokens']])
    expected_removed = "    return enumerate(tqdm_class(iterable, start, **tqdm_kwargs))\n"
    assert actual_removed == expected_removed, \
        "data from '-' annotation matches expected removed line"
    actual_added = ''.join([x[2]  # value, that is, text_fragment
                            for x in patch[changed_file_name]['+'][0]['tokens']])
    expected_added = "    return enumerate(tqdm_class(iterable, **tqdm_kwargs), start)\n"
    assert actual_added == expected_added, \
        "data from '+' annotation matches expected added line"
    # - check position in hunk
    hunk_line_no = 3   # there are usually 3 context lines before the change
    hunk_line_no += 1  # first there is single removed line (for one changed line)
    assert patch[changed_file_name]['-'][0]['id'] + 1 == hunk_line_no, \
        "index of line in hunk for '-' annotation matches the patch"
    hunk_line_no += 1  # then there is single added line (for one changed line)
    assert patch[changed_file_name]['+'][0]['id'] + 1 == hunk_line_no, \
        "index of line in hunk for '+' annotation matches the patch"
    # - check type
    assert patch[changed_file_name]['-'][0]['type'] == 'code', \
        "removed line is marked as code"
    assert patch[changed_file_name]['+'][0]['type'] == 'code', \
        "added line is marked as code"

    # documentation patch
    file_path = 'test_dataset/unidiff-1/3353080f357a36c53d21c2464ece041b100075a1.diff'
    patch = annotate_single_diff(file_path)
    # check file data
    assert 'README.rst' in patch, \
        "correct file name is used in patch data"
    assert patch['README.rst']['purpose'] == 'documentation', \
        "'README.rst' file purpose is documentation"
    # check line data
    pre_image_lines = patch['README.rst']['-']
    post_image_lines = patch['README.rst']['+']
    assert all([line['purpose'] == 'documentation'
                for line in pre_image_lines]), \
        "all pre-image lines of 'README.rst' are marked as documentation"
    assert all([line['purpose'] == 'documentation'
                for line in post_image_lines]), \
        "all post-image lines of 'README.rst' are marked as documentation"

    file_path = 'test_dataset/empty.diff'
    patch = annotate_single_diff(file_path)
    assert patch == {}, "empty patch on empty diff"

    file_path = 'test_dataset/this_patch_does_not_exist.diff'
    with pytest.raises(FileNotFoundError):
        annotate_single_diff(file_path)


def test_Bug_constructor():
    # code patch
    file_path = Path('test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff')
    # fiddle around if path does not have the default structure
    saved_patches_dir = None
    if file_path.parts[-2] != Bug.PATCHES_DIR:
        saved_patches_dir = Bug.PATCHES_DIR
        Bug.PATCHES_DIR = ""

    bug = Bug('test_dataset', 'tqdm-1')
    assert file_path.name in bug.patches, \
        "retrieved annotations for the single *.diff file"
    assert len(bug.patches) == 1, \
        "there was only 1 patch file for a bug"
    assert "tqdm/contrib/__init__.py" in bug.patches[file_path.name], \
        "there is expected changed file in a bug patch"

    # un-fiddle, if needed
    if saved_patches_dir is not None:
        Bug.PATCHES_DIR = saved_patches_dir


def test_Bug_save(tmp_path: Path):
    bug = Bug('test_dataset_structured', 'keras-10')  # the one with the expected directory structure
    bug.save(tmp_path)

    save_path = tmp_path.joinpath('keras-10', Bug.ANNOTATIONS_DIR)
    assert save_path.exists(), \
        "directory path to save data exists"
    assert save_path.is_dir(), \
        "directory path to save data is directory"
    assert len(list(save_path.iterdir())) == 1, \
        "there is only one file saved in save directory"
    assert len(list(save_path.glob("*.json"))) == 1, \
        "there is only one JSON file saved in save directory"
    assert save_path.joinpath('c1c4afe60b1355a6c0e83577791a0423f37a3324.json').is_file(), \
        "this JSON file has expected filename"


def test_BugDataset():
    bugs = BugDataset('test_dataset_structured')
    print(f"{bugs.bugs=}")

    assert len(bugs) >= 1, \
        "there is at least one bug in the dataset"
    assert 'keras-10' in bugs, \
        "the bug with 'keras-10' identifier is included in the dataset"
    assert bugs.bugs == list(bugs), \
        "iterating over bug identifiers works as expected"

    bug = bugs.get_bug('keras-10')
    assert isinstance(bug, Bug), \
        "get_bug() method returns Bug object"


class TestCLexer:
    # Create a lexer instance
    lexer = CLexer()

    def test_splitting_tokens(self):
        # iterable of (index, token_type, value), where `index` is the starting
        # position of the token within the input text; value might consist
        # of multiple lines
        tokens_unprocessed = self.lexer.get_tokens_unprocessed(example_C_code)
        tokens_split = split_multiline_lex_tokens(tokens_unprocessed)

        # we need list for further analysis, not a generator
        tokens_split = list(tokens_split)

        for index, token_type, text_fragment in tokens_split:
            assert text_fragment.count('\n') <= 1, \
                "each text_fragment has at most one newline"

        for i, elem in enumerate(tokens_split):
            idx_curr = elem[0]
            try:
                idx_next = tokens_split[i + 1][0]
            except IndexError:
                idx_next = None

            extracted = example_C_code[idx_curr:idx_next]
            assert extracted == elem[2], \
                f"{i}: index is updated correctly to point to text_fragment"

        assert ''.join([x[2] for x in tokens_split]) == example_C_code, \
            "all text_fragments concatenate to original code"

    def test_group_split_tokens_by_line(self):
        tokens_unprocessed = self.lexer.get_tokens_unprocessed(example_C_code)
        tokens_split = split_multiline_lex_tokens(tokens_unprocessed)

        code_to_group = example_C_code
        tokens_grouped = group_tokens_by_line(code_to_group, tokens_split)

        lines = code_to_group.splitlines(keepends=True)

        assert len(lines) == len(tokens_grouped), \
            "number of lines in code match numbers of token groups"

        for i, line in enumerate(lines):
            assert line == ''.join([x[2] for x in tokens_grouped[i]]), \
                "text_fragments for tokens belonging to a line concatenate to that line"

    def test_line_is_comment(self):
        tokens_unprocessed = self.lexer.get_tokens_unprocessed(example_C_code)
        tokens_split = split_multiline_lex_tokens(tokens_unprocessed)
        tokens_grouped = group_tokens_by_line(example_C_code, tokens_split)

        actual = {
            i: line_is_comment(line_tokens)
            for i, line_tokens in tokens_grouped.items()
        }

        assert len(actual) == len(example_C_code.splitlines(keepends=True)), \
            "numbers of lines matches with code"

        # NOTE: these tests *must* be updated it example_C_code changes
        assert not actual[5], \
            "last line in example code is not a comment"
        assert all([v for k, v in actual.items() if k != 5]), \
            "all but last line in example code is a comment"

# end of test_annotate.py
