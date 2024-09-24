import copy
import re
from pathlib import Path
from textwrap import dedent

from pygments.lexers import CLexer
from pygments.token import Token
import pytest
import unidiff

from diffannotator.annotate import (split_multiline_lex_tokens, line_ends_idx,
                                    group_tokens_by_line, front_fill_gaps, deep_update,
                                    clean_text, line_is_comment, annotate_single_diff,
                                    Bug, BugDataset, AnnotatedPatchedFile, AnnotatedHunk)
from diffannotator.utils.git import GitRepo

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
    text_to_clean = "some text with * / \\ \t and\nnew\nlines     and  spaces"
    expected = "some text with andnewlines and spaces"
    actual = clean_text(text_to_clean)

    assert actual == expected


def test_post_image_from_diff():
    file_path = 'tests/test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'
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
    file_path = 'tests/test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'
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
    file_path = 'tests/test_dataset/unidiff-1/3353080f357a36c53d21c2464ece041b100075a1.diff'
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

    file_path = 'tests/test_dataset/empty.diff'
    patch = annotate_single_diff(file_path)
    assert patch == {}, "empty patch on empty diff"

    file_path = 'tests/test_dataset/this_patch_does_not_exist.diff'
    with pytest.raises(FileNotFoundError):
        annotate_single_diff(file_path)


@pytest.mark.parametrize("line_type", [unidiff.LINE_TYPE_REMOVED, unidiff.LINE_TYPE_ADDED])
def test_AnnotatedPatchedFile(line_type):
    # code patch
    file_path = 'tests/test_dataset_structured/keras-10/patches/c1c4afe60b1355a6c0e83577791a0423f37a3324.diff'

    # create AnnotatedPatchedFile object
    patch_set = unidiff.PatchSet.from_filename(file_path, encoding="utf-8")
    patched_file = AnnotatedPatchedFile(patch_set[0])

    # add contents of pre-image and post-image
    files_path = Path('tests/test_dataset_structured/keras-10/files')  # must agree with `file_path`
    src_path = files_path / 'a' / Path(patched_file.source_file).name
    dst_path = files_path / 'b' / Path(patched_file.source_file).name
    patched_file = patched_file.add_sources_from_files(src_path, dst_path)

    src_text = src_path.read_text(encoding="utf-8")
    dst_text = dst_path.read_text(encoding="utf-8")
    assert patched_file.image_for_type('-') == src_text, \
        "image_for_type returns pre-image for '-'"
    assert patched_file.image_for_type('+') == dst_text, \
        "image_for_type returns post-image for '+'"

    src_tokens = patched_file.tokens_for_type(line_type)
    #print(f"{src_tokens[:2]}")
    assert src_tokens is not None, \
        f"tokens_for_type returns something for '{line_type}'"
    assert len(list(src_tokens)) > 0, \
        f"tokens_for_type returns non-empty iterable of tokens for '{line_type}'"

    first_hunk = patched_file.patched_file[0]
    first_hunk = AnnotatedHunk(patched_file=patched_file, hunk=first_hunk)
    bare_hunk_data = first_hunk.process()
    #print(f"{bare_hunk_data=}")
    bare_hunk_tokens = {line_data['id']: line_data['tokens'] for line_data
                        in bare_hunk_data['keras/engine/training_utils.py'][line_type]}
    #print(f"{bare_hunk_tokens=}")
    bare_tokens_renumbered = {
        i: bare_hunk_tokens[idx] for i, idx in zip(range(len(bare_hunk_tokens)), bare_hunk_tokens.keys())
    }
    bare_lines_renumbered = {
        i: "".join([tok[2] for tok in tokens])
        for i, tokens in bare_tokens_renumbered.items()
    }
    #print(f"{bare_tokens_renumbered=}")
    #print(f"{bare_lines_renumbered=}")

    tokens_for_hunk = patched_file.hunk_tokens_for_type(line_type, first_hunk.hunk)
    hunk_tokens = first_hunk.tokens_for_type(line_type)
    assert tokens_for_hunk == hunk_tokens, \
        f"Both ways of getting tokens for {'removed' if line_type == '-' else 'added'} lines return same result"
    #print(f"{tokens_for_hunk=}")
    tokens_renumbered = {
        i: tokens_for_hunk[idx] for i, idx in zip(range(len(tokens_for_hunk)), tokens_for_hunk.keys())
    }
    lines_renumbered = {
        i: "".join([tok[2] for tok in tokens])
        for i, tokens in tokens_renumbered.items()
    }
    #print(f"{tokens_renumbered=}")
    #print(f"{lines_renumbered=}")
    #tokens_sel = patched_file.tokens_range_for_type('-', 432-1, 7)
    #for k, v in tokens_sel.items():
    #    print(f"{k}: {v}")

    assert bare_lines_renumbered == lines_renumbered, \
        "AnnotatedHunk.process() and AnnotatedPatchedFile.hunk_tokens_for_type() give the same lines"
    assert bare_tokens_renumbered != tokens_renumbered, \
        "lexing pre-image from diff is not the same as lexing whole pre-image file, in this case"


def test_Bug_from_dataset():
    # code patch
    file_path = Path('tests/test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff')

    bug = Bug.from_dataset('tests/test_dataset', 'tqdm-1',
                           patches_dir="", annotations_dir="")
    assert file_path.name in bug.patches, \
        "retrieved annotations for the single *.diff file"
    assert len(bug.patches) == 1, \
        "there was only 1 patch file for a bug"
    assert "tqdm/contrib/__init__.py" in bug.patches[file_path.name], \
        "there is expected changed file in a bug patch"


def test_Bug_from_dataset_with_fanout():
    # code patch
    file_path = 'tests/test_dataset_fanout/tqdm-1/c0/dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'

    commit_id = '/'.join(Path(file_path).parts[-2:])
    bug = Bug.from_dataset('tests/test_dataset_fanout', 'tqdm-1',
                           patches_dir="", annotations_dir="", fan_out=True)

    assert commit_id in bug.patches, \
        "retrieved annotations for the single *.diff file"
    assert len(bug.patches) == 1, \
        "there was only 1 patch file for a bug"
    assert "tqdm/contrib/__init__.py" in bug.patches[commit_id], \
        "there is expected changed file in a bug patch"


def test_Bug_from_patchset():
    file_path = 'tests/test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff'
    patch = unidiff.PatchSet.from_filename(file_path, encoding='utf-8')

    commit_id = Path(file_path).stem
    bug = Bug.from_patchset(patch_id=commit_id, patch_set=patch)
    assert commit_id in bug.patches, \
        "retrieved annotations for the single patchset"
    assert len(bug.patches) == 1, \
        "there was only 1 patchset for a bug"
    assert "tqdm/contrib/__init__.py" in bug.patches[commit_id], \
        "there is expected changed file in a bug patch"


def test_Bug_save(tmp_path: Path):
    bug = Bug.from_dataset('tests/test_dataset_structured', 'keras-10')  # the one with the expected directory structure
    bug.save(tmp_path)

    save_path = tmp_path.joinpath('keras-10', Bug.DEFAULT_ANNOTATIONS_DIR)
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


def test_Bug_save_with_fanout(tmp_path: Path):
    bug = Bug.from_dataset('tests/test_dataset_structured', 'keras-10')  # the one with the expected directory structure
    bug.save(tmp_path, fan_out=True)

    save_path = tmp_path.joinpath('keras-10', Bug.DEFAULT_ANNOTATIONS_DIR)
    assert save_path.joinpath('c1', 'c4afe60b1355a6c0e83577791a0423f37a3324.json').is_file(), \
        "JSON file was saved with fan-out"


def test_BugDataset_from_directory():
    bugs = BugDataset.from_directory('tests/test_dataset_structured')

    assert len(bugs) >= 1, \
        "there is at least one bug in the dataset"
    assert 'keras-10' in bugs, \
        "the bug with 'keras-10' identifier is included in the dataset"
    assert bugs.bug_ids == list(bugs), \
        "iterating over bug identifiers works as expected"

    bug = bugs.get_bug('keras-10')
    assert isinstance(bug, Bug), \
        "get_bug() method returns Bug object"


def test_BugDataset_from_directory_with_fanout():
    bugs = BugDataset.from_directory(dataset_dir='tests/test_dataset_fanout',
                                     patches_dir='', annotations_dir='', fan_out=True)

    bug = bugs.get_bug('tqdm-1')
    assert isinstance(bug, Bug), \
        "get_bug() method returns Bug object"
    assert len(bug.patches) == 1, \
        "there is exactly 1 patch for 'tqdm-1' bug"


# MAYBE: mark that it requires network
@pytest.mark.slow
def test_BugDataset_from_repo(tmp_path: Path):
    # MAYBE: create a global variable in __init__.py
    sha1_re = re.compile(r"^[0-9a-fA-F]{40}$")  # SHA-1 identifier is 40 hex digits long
    # MAYBE: create fixture
    test_repo_url = 'https://github.com/githubtraining/hellogitworld.git'
    repo = GitRepo.clone_repository(
        repository=test_repo_url,
        working_dir=tmp_path,
        make_path_absolute=True,
    )

    bugs = BugDataset.from_repo(repo, revision_range=('-3', 'HEAD'))

    assert len(bugs) == 3, \
        "we got 3 commit ids we expected from `git log -3 HEAD` in the dataset"
    assert all([re.fullmatch(sha1_re, bug_id)
                for bug_id in bugs.bug_ids]), \
        "all bug ids in the dataset look like SHA-1"
    assert bugs._dataset_path is None, \
        "there is no path to a dataset directory stored in BugDataset"
    assert bugs._patches is not None, \
        "patches data is present in _patches field"
    assert bugs.bug_ids == list(bugs._patches.keys()), \
        "there is 1-to-1 correspondence between bug ids and keys to patch data"

    annotated_data = list(bugs.iter_bugs())

    assert len(annotated_data) == 3, \
        "we got 3 annotated bugs we expected from `git log -3 HEAD`"
    assert all([isinstance(bug, Bug)
                for bug in annotated_data]), \
        "all elements of bugs.get_bugs() are Bug objects"
    assert all([len(bug.patches) == 1 and list(bug.patches.items())[0][0] == bug_id
                for bug_id, bug in zip(bugs.bug_ids, annotated_data)]), \
        "all bugs remember their ids correctly"


def test_line_callback_trivial():
    # code patch
    file_path = Path('tests/test_dataset/tqdm-1/c0dcf39b046d1b4ff6de14ac99ad9a1b10487512.diff')

    # trivial callback
    line_type = "any"
    AnnotatedPatchedFile.line_callback = lambda tokens: line_type
    patch = annotate_single_diff(file_path)

    # - check file
    changed_file_name = 'tqdm/contrib/__init__.py'
    assert changed_file_name in patch, \
        "correct file name is used in patch data"
    # - check type
    assert patch[changed_file_name]['-'][0]['type'] == line_type, \
        f"removed line is marked as '{line_type}' by lambda callback"
    assert patch[changed_file_name]['+'][0]['type'] == line_type, \
        f"added line is marked as '{line_type}' by lambda callback"

    # use exec
    code_str = f"""return '{line_type}'"""
    callback_code_str = ("def callback_x(tokens):\n" +
                         "  " + "\n  ".join(code_str.splitlines()) + "\n")
    exec(callback_code_str, globals())
    AnnotatedPatchedFile.line_callback = \
        locals().get('callback_x',
                     globals().get('callback_x', None))
    patch = annotate_single_diff(file_path)

    assert patch[changed_file_name]['-'][0]['type'] == line_type, \
        f"removed line is marked as '{line_type}' by self-contained exec callback"
    assert patch[changed_file_name]['+'][0]['type'] == line_type, \
        f"added line is marked as '{line_type}' by self-contained exec callback"


def test_line_callback_whitespace():
    # code patch
    file_path = Path('tests/test_dataset_structured/keras-10/patches/c1c4afe60b1355a6c0e83577791a0423f37a3324.diff')

    # complex callback, untyped
    def detect_all_whitespace_line(tokens):
        if len(tokens) == 0:
            return "empty"
        elif all([token_type in Token.Text.Whitespace or
                  token_type in Token.Text and text_fragment.isspace()
                  for _, token_type, text_fragment in tokens]):
            return "whitespace"
        else:
            return None

    AnnotatedPatchedFile.line_callback = detect_all_whitespace_line
    patch = annotate_single_diff(file_path)

    changed_file_name = 'keras/engine/training_utils.py'
    assert changed_file_name in patch, \
        f"there is '{changed_file_name}' file used in patch data"
    assert any([elem['type'] == 'whitespace'
                for elem in patch[changed_file_name]['-']]), \
        f"at least one whitespace only line in pre-image of '{changed_file_name}'"
    assert any([elem['type'] == 'whitespace'
                for elem in patch[changed_file_name]['+']]), \
        f"at least one whitespace only line in post-image of '{changed_file_name}'"

    # define callback using string
    callback_code = dedent("""\
    # this could be written using ternary conditional operator
    if len(tokens) == 1 and tokens[0][2] == '\\n':
        return 'empty'
    else:
        return None
    """)
    AnnotatedPatchedFile.line_callback = \
        AnnotatedPatchedFile.make_line_callback(callback_code)

    assert AnnotatedPatchedFile.line_callback is not None, \
        "successfully created the callback code from callback string"

    # annotate with the new callback
    patch = annotate_single_diff(file_path)

    assert any([elem['type'] == 'empty'
                for elem in patch[changed_file_name]['-']]), \
        f"at least one empty line in pre-image of '{changed_file_name}'"
    assert any([elem['type'] == 'empty'
                for elem in patch[changed_file_name]['+']]), \
        f"at least one empty line in post-image of '{changed_file_name}'"


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
        assert not actual[len(actual)-1], \
            "last line in example code is not a comment"
        assert all([v for k, v in actual.items() if k != len(actual)-1]), \
            "all but last line in example code is a comment"

# end of test_annotate.py
