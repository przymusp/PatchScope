#!/usr/bin/env python
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, TypeVar
# NOTE: Callable should be imported from collections.abc for newer Python
from typing import Callable

import tqdm
import typer
from typing_extensions import Annotated

from .annotate import Bug


PathLike = TypeVar("PathLike", str, bytes, Path, os.PathLike)
T = TypeVar('T')  # Declare type variable "T" to use in typing

app = typer.Typer(no_args_is_help=True, add_completion=False)


class PurposeCounterResults:
    """Override this datastructure to gather results"""

    def __init__(self, processed_files: list,
                 hunk_purposes: Counter[str], added_line_purposes: Counter[str], removed_line_purposes: Counter[str]):
        self._processed_files = processed_files
        self._hunk_purposes = hunk_purposes
        self._added_line_purposes = added_line_purposes
        self._removed_line_purposes = removed_line_purposes

    def __add__(self, other: 'PurposeCounterResults') -> 'PurposeCounterResults':
        if isinstance(other, PurposeCounterResults):
            new_instance = PurposeCounterResults(
                self._processed_files + other._processed_files,
                self._hunk_purposes + other._hunk_purposes,
                self._added_line_purposes + other._added_line_purposes,
                self._removed_line_purposes + other._removed_line_purposes)
            return new_instance

    def __repr__(self) -> str:
        return f"PurposeCounterResults(_processed_files={self._processed_files!r}, " \
               f"_hunk_purposes={self._hunk_purposes!r}, " \
               f"_added_line_purposes={self._added_line_purposes!r}, " \
               f"_removed_line_purposes)={self._removed_line_purposes!r})"

    def to_dict(self) -> dict:
        return {
            "processed_files": self._processed_files,
            "hunk_purposes": self._hunk_purposes,
            "added_line_purposes": self._added_line_purposes,
            "removed_line_purposes": self._removed_line_purposes,
        }

    @staticmethod
    def default() -> 'PurposeCounterResults':
        """
        Constructs empty datastructure to work as 0 for addition via "+"

        :return: empty datastructure
        """
        return PurposeCounterResults([], Counter(), Counter(), Counter())

    @staticmethod
    def create(file_path: str, data: dict) -> 'PurposeCounterResults':
        """
        Override this function for single annotation handling

        :param file_path: path to processed file
        :param data: dictionary with annotations (file content)
        :return: datastructure instance
        """
        file_purposes = Counter()
        added_line_purposes = Counter()
        removed_line_purposes = Counter()
        for change_file in data:
            if 'purpose' not in data[change_file] and change_file == 'commit_metadata':
                # this is not changed file information, but commit metadata
                continue
            # TODO: log info / debug
            #print(change_file)
            #print(data[change_file]['purpose'])
            file_purposes[data[change_file]['purpose']] += 1
            if '+' in data[change_file]:
                added_lines = data[change_file]['+']
                for added_line in added_lines:
                    added_line_purposes[added_line['purpose']] += 1
            if '-' in data[change_file]:
                removed_lines = data[change_file]['-']
                for removed_line in removed_lines:
                    removed_line_purposes[removed_line['purpose']] += 1
        return PurposeCounterResults([file_path], file_purposes, added_line_purposes, removed_line_purposes)


class AnnotatedFile:
    """Annotated single file in specific bug"""

    def __init__(self, file_path: PathLike):
        """Constructor of the annotated file of specific bug

        :param file_path: path to the single file
        """
        self._path = Path(file_path)

    def gather_data(self, bug_mapper: Callable[..., T],
                    **mapper_kwargs) -> T:
        """
        Retrieves data from file

        :param bug_mapper: function to map bug to datastructure
        :return: resulting datastructure
        """
        with self._path.open('r') as json_file:
            data = json.load(json_file)
            return bug_mapper(str(self._path), data, **mapper_kwargs)


class AnnotatedBug:
    """Annotated bug class"""

    def __init__(self, bug_dir: PathLike, annotations_dir: str = Bug.DEFAULT_ANNOTATIONS_DIR):
        """Constructor of the annotated bug

        :param bug_dir: path to the single bug
        """
        self._path = Path(bug_dir)
        self._annotations_path = self._path / annotations_dir

        try:
            self.annotations = [str(d.name) for d in self._annotations_path.iterdir()]
        except Exception as ex:
            print(f"Error in AnnotatedBug for '{self._path}': {ex}")

    def gather_data(self, bug_mapper: Callable[..., T],
                    datastructure_generator: Callable[[], T],
                    **mapper_kwargs) -> T:
        """
        Gathers dataset data via processing each file in current bug using AnnotatedFile class and provided functions

        :param bug_mapper: function to map bug to datastructure
        :param datastructure_generator: function to create empty datastructure to combine results via "+"
        :return: combined datastructure with all files data
        """
        combined_results = datastructure_generator()
        for annotation in self.annotations:
            if '...' in annotation:
                continue
            annotation_file_path = self._annotations_path / annotation
            annotation_file = AnnotatedFile(annotation_file_path)
            file_results = annotation_file.gather_data(bug_mapper, **mapper_kwargs)
            combined_results += file_results
        return combined_results

    def gather_data_dict(self, bug_dict_mapper: Callable[..., dict],
                         **mapper_kwargs) -> dict:
        """
        Gathers dataset data via processing each file in current bug using AnnotatedFile class and provided functions

        :param bug_dict_mapper: function to map diff to dictionary
        :return: combined dictionary of all diffs
        """
        combined_results = {}
        for annotation in self.annotations:
            if '...' in annotation:
                continue
            annotation_file_path = self._annotations_path / annotation
            annotation_file = AnnotatedFile(annotation_file_path)
            diff_file_results = annotation_file.gather_data(bug_dict_mapper, **mapper_kwargs)
            combined_results |= {str(annotation): diff_file_results}
        return combined_results


class AnnotatedBugDataset:
    """Annotated bugs dataset class"""

    def __init__(self, dataset_dir: PathLike):
        """Constructor of the annotated bug dataset.

        :param dataset_dir: path to the dataset
        """
        self._path = Path(dataset_dir)
        self.bugs: List[str] = []

        try:
            self.bugs = [str(d.name) for d in self._path.iterdir()
                         if d.is_dir()]
        except Exception as ex:
            print(f"Error in AnnotatedBugDataset for '{self._path}': {ex}")

    def gather_data(self, bug_mapper: Callable[..., T],
                    datastructure_generator: Callable[[], T],
                    annotations_dir: str = Bug.DEFAULT_ANNOTATIONS_DIR,
                    **mapper_kwargs) -> T:
        """
        Gathers dataset data via processing each bug using AnnotatedBug class and provided functions

        :param bug_mapper: function to map bug to datastructure
        :param datastructure_generator: function to create empty datastructure to combine results via "+"
        :param annotations_dir: subdirectory where annotations are; path
            to annotation in a dataset is <bug_id>/<annotations_dir>/<patch_data>.json
        :return: combined datastructure with all bug data
        """
        combined_results = datastructure_generator()

        print(f"Gathering data from bugs/patches in '{self._path}' directory.")
        for bug_id in tqdm.tqdm(self.bugs, desc='bug'):
            # TODO: log info / debug
            #print(bug_id)
            bug_path = self._path / bug_id
            bug = AnnotatedBug(bug_path, annotations_dir=annotations_dir)
            bug_results = bug.gather_data(bug_mapper, datastructure_generator, **mapper_kwargs)
            combined_results += bug_results

        return combined_results

    def gather_data_dict(self, bug_dict_mapper: Callable[..., dict],
                         annotations_dir: str = Bug.DEFAULT_ANNOTATIONS_DIR,
                         **mapper_kwargs) -> dict:
        """
        Gathers dataset data via processing each bug using AnnotatedBug class and provided function

        :param bug_dict_mapper: function to map diff to dictionary
        :param annotations_dir: subdirectory where annotations are; path
            to annotation in a dataset is <bug_id>/<annotations_dir>/<patch_data>.json
        :return: combined dictionary of all bugs
        """
        combined_results = {}
        for bug_id in tqdm.tqdm(self.bugs):
            print(bug_id)
            bug_path = self._path / bug_id
            bug = AnnotatedBug(bug_path, annotations_dir=annotations_dir)
            bug_results = bug.gather_data_dict(bug_dict_mapper, **mapper_kwargs)
            combined_results |= {bug_id: bug_results}
        return combined_results

    def gather_data_list(self, bug_to_dict_mapper: Callable[..., dict],
                         annotations_dir: str = Bug.DEFAULT_ANNOTATIONS_DIR,
                         **mapper_kwargs) -> list:
        """
        Gathers dataset data via processing each bug using AnnotatedBug class and provided function

        :param bug_to_dict_mapper: function to map diff annotations to dictionary
        :param annotations_dir: subdirectory where annotations are; path
            to annotation in a dataset is <bug_id>/<annotations_dir>/<patch_data>.json
        :return: list of bug dictionaries
        """
        combined_results = []
        for bug_id in tqdm.tqdm(self.bugs, desc="patchset", position=2, leave=False):
            bug_path = self._path / bug_id
            bug = AnnotatedBug(bug_path, annotations_dir=annotations_dir)
            bug_results = bug.gather_data_dict(bug_to_dict_mapper, **mapper_kwargs)
            # NOTE: could have used `+=` instead of `.append()`
            for patch_id, patch_data in bug_results.items():
                combined_results.append({
                    'bug_id': bug_id,
                    'patch_id': patch_id,
                    **patch_data
                })

        return combined_results


def map_diff_to_purpose_dict(_diff_file_path: str, data: dict) -> dict:
    """Extracts file purposes of changed file in a diff annotation

    Returns mapping from file name (of a changed file) to list (???)
    of file purposes for that file.

    Example:

        {
            'keras/engine/training_utils.py': ['programming'],
            'tests/keras/engine/test_training.py': ['test'],
        }

    :param _diff_file_path: file path containing diff, ignored
    :param data: dictionary loaded from file
    :return: dictionary with file purposes
    """
    result = {}
    for change_file in data:
        if 'purpose' not in data[change_file] and change_file == 'commit_metadata':
            # this is not changed file information, but commit metadata
            continue

        #print(change_file)
        #print(data[change_file]['purpose'])
        if change_file not in result:
            result[change_file] = []
        result[change_file].append(data[change_file]['purpose'])

    #print(f"{_diff_file_path}:{result=}")
    return result


def map_diff_to_lines_stats(annotation_file_basename: str,
                            annotation_data: dict) -> dict:
    """Mapper passed by line_stats() to *.gather_data_dict() method

    It gathers information about file, and counts information about
    changed lines (in pre-image i.e. "-", in post-image i.e. "+",...).

    :param annotation_file_basename: name of JSON file with annotation data
    :param annotation_data: parsed annotations data, retrieved from
        `annotation_file_basename` file.
    """
    # Example fragment of annotation file:
    #
    # {
    #   "third_party/xla/xla/service/gpu/ir_emitter_unnested.cc": {
    #     "language": "C++",
    #     "type": "programming",
    #     "purpose": "programming",
    #     "+": [
    #       {
    #         "id": 4,
    #         "type": "code",
    #         "purpose": "programming",
    #         "tokens": […],
    #       },
    #       {"id":…},
    #     ],
    #     "-": […],
    #   },…
    # }
    result = {}
    # TODO: replace commented out DEBUG lines with logging (info or debug)
    # DEBUG
    #print(f"map_diff_to_lines_stats('{annotation_file_basename}', {{...}}):")
    for filename, file_data in annotation_data.items():
        # DEBUG
        #print(f" {filename=}")
        # NOTE: each file should be present only once for given patch/commit
        if filename in result:
            print(f"Warning: '{filename}' file present more than once in '{annotation_file_basename}'")

        if filename not in result:
            # per-file data
            result[filename] = {
                key: value for key, value in file_data.items()
                if key in {"language", "type", "purpose"}
            }
            # DEBUG
            #print(f"  {result[filename]=}")
            # summary of per-line data
            result[filename].update({
                "+": Counter(),
                "-": Counter(),
                "+/-": Counter(),  # probably not necessary
            })
            # DEBUG
            #print(f"  {result[filename]=}")

        # DEBUG
        #print(f"  {type(file_data)=}, {file_data.keys()=}")

        for line_type in "+-":  # str used as iterable
            # diff might have removed lines, or any added lines
            if line_type not in file_data:
                continue

            for line in file_data[line_type]:
                result[filename][line_type]["count"] += 1  # count of added/removed lines

                for data_type in ["type", "purpose"]:  # ignore "id" and "tokens" fields
                    line_data = line[data_type]
                    result[filename][line_type][f"{data_type}.{line_data}"] += 1
                    result[filename]["+/-"][f"{data_type}.{line_data}"] += 1

    return result


def map_diff_to_timeline(annotation_file_basename: str,
                         annotation_data: dict) -> dict:
    """Mapper passed by timeline() to *.gather_data_dict() method

    It gathers information about file, and counts information about
    changed lines (in pre-image i.e. "-", in post-image i.e. "+",...).

    :param annotation_file_basename: name of JSON file with annotation data
    :param annotation_data: parsed annotations data, retrieved from
        `annotation_file_basename` file.
    """
    # Example fragment of annotation file:
    #
    # {
    #   "commit_metadata": {
    #     "id": "e54746bdf7d5c831eabe4dcea76a7626f1de73df",
    #     "parents": ["93b61589b0bdb3845ee839e9c2a4e1adb06bd483"],
    #     "tree": "262d65e6c945adfa2d64bfe51e70c09d2e1d7d06",
    #     "author": {
    #       "author": "Patrick Cloke <clokep@users.noreply.github.com>",
    #       "name": "Patrick Cloke",
    #       "email": "clokep@users.noreply.github.com",
    #       "timestamp": 1611763190,
    #       "tz_info": "-0500"
    #     },
    #     "committer": {
    #       "committer": "GitHub <noreply@github.com>",
    #       "name": "GitHub",
    #       "email": "noreply@github.com",
    #       "timestamp": 1611763190,
    #       "tz_info": "-0500"
    #     },
    #   },
    #   "third_party/xla/xla/service/gpu/ir_emitter_unnested.cc": {
    #     "language": "C++",
    #     "type": "programming",
    #     "purpose": "programming",
    #     "+": [
    #       {
    #         "id": 4,
    #         "type": "code",
    #         "purpose": "programming",
    #         "tokens": […],
    #       },
    #       {"id":…},
    #     ],
    #     "-": […],
    #   },…
    # }

    # TODO: add logging (info or debug)
    result = Counter()
    per_commit_info = {}

    # gather summary data from all changed files
    for filename, file_data in annotation_data.items():
        # NOTE: each file should be present only once for given patch/commit

        if filename == 'commit_metadata':
            # this might be changed file information, but commit metadata
            for metadata_key in ('author', 'committer'):
                if metadata_key not in file_data:
                    continue
                authorship_data = file_data[metadata_key]
                for authorship_key in ('timestamp', 'tz_info', 'name', 'email'):
                    if authorship_key in authorship_data:
                        per_commit_info[f"{metadata_key}.{authorship_key}"] = file_data[metadata_key][authorship_key]

            if 'parents' in file_data:
                per_commit_info['n_parents'] = len(file_data['parents'])

            if 'purpose' not in file_data:
                # commit metadata, skip processing it as a file
                continue
            else:
                print(f"  warning: found file named 'commit_metadata' in {annotation_file_basename}")

        result['file_names'] += 1

        # gather per-file information, and aggregate it
        per_file_data = {
            key: value for key, value in file_data.items()
            if key in ("language", "type", "purpose")
        }
        per_file_data.update({
            "+": Counter(),
            "-": Counter(),
        })

        for line_type in "+-":  # str used as iterable
            # diff might have removed lines, or any added lines
            if line_type not in file_data:
                continue

            for line in file_data[line_type]:
                per_file_data[line_type]["count"] += 1  # count of added/removed lines

                for data_type in ["type", "purpose"]:  # ignore "id" and "tokens" fields
                    line_data = line[data_type]
                    per_file_data[line_type][f"{data_type}.{line_data}"] += 1

        for key, value in per_file_data.items():
            if isinstance(value, (dict, defaultdict, Counter)):
                for sub_key, sub_value in value.items():
                    # don't expect anything deeper
                    result[f"{key}:{sub_key}"] += sub_value
            elif isinstance(value, int):
                result[key] += value
            else:
                result[f"{key}:{value}"] += 1

    result = dict(result, **per_commit_info)

    return result



# TODO: make it common (move it to 'utils' module or '__init__.py' file)
def save_result(result: Any, result_json: Path) -> None:
    """Serialize `result` and save it in `result_json` JSON file

    Side effects:

    - prints progress information to stdout
    - creates parent directory if it does not exist

    :param result: data to serialize and save
    :param result_json: path to JSON file to save `result` to
    """
    print(f"Saving results to '{result_json}' JSON file")

    # ensure that parent directory exists, so we can save the file
    parent_dir = result_json.parent
    if not parent_dir.exists():
        print(f"- creating '{parent_dir}' directory")
        parent_dir.mkdir(parents=True, exist_ok=True)  # exist_ok=True for race condition

    with result_json.open(mode='w') as result_f:
        json.dump(result, result_f, indent=4)


# implementing options common to all subcommands
# see https://jacobian.org/til/common-arguments-with-typer/
@app.callback()
def common(
    ctx: typer.Context,
    annotations_dir: Annotated[
        str,
        typer.Option(
            metavar="DIR_NAME",
            help="Subdirectory to read annotations from; use '' to do without such"
        )
    ] = Bug.DEFAULT_ANNOTATIONS_DIR,
) -> None:
    # if anything is printed by this function, it needs to utilize context
    # to not break installed shell completion for the command
    # see https://typer.tiangolo.com/tutorial/options/callback-and-context/#fix-completion-using-the-context
    if ctx.resilient_parsing:
        return

    # pass to subcommands via context
    ctx.obj = SimpleNamespace(
        annotations_dir=annotations_dir,
    )


@app.command()
def purpose_counter(
    ctx: typer.Context,
    datasets: Annotated[
        List[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=False
        )
    ],
    result_json: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            dir_okay=False,
            metavar="JSON_FILE",
            help="JSON file to write gathered results to",
        )
    ] = None,
) -> None:
    """Calculate count of purposes from all bugs in provided datasets

    Each dataset is expected to be existing directory with the following
    structure:

        <dataset_directory>/<bug_directory>/annotation/<patch_file>.json

    Each dataset can consist of many BUGs, each BUG should include patch
    of annotated *diff.json file in 'annotation/' subdirectory.
    """
    result = {}
    for dataset in datasets:
        print(f"Dataset {dataset}")
        annotated_bugs = AnnotatedBugDataset(dataset)
        data = annotated_bugs.gather_data(PurposeCounterResults.create,
                                          PurposeCounterResults.default,
                                          annotations_dir=ctx.obj.annotations_dir)
        result[dataset] = data

    if result_json is None:
        print(result)
    else:
        save_result({
                        str(key): value.to_dict()
                        for key, value in result.items()
                    },
                    result_json)


@app.command()
def purpose_per_file(
    ctx: typer.Context,
    result_json: Annotated[
        Path,
        typer.Argument(
            dir_okay=False,
            help="JSON file to write gathered results to"
        )
    ],
    datasets: Annotated[
        List[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=False,
            help="list of dirs with datasets to process"
        )
    ],
) -> None:
    """Calculate per-file count of purposes from all bugs in provided datasets

    Each dataset is expected to be existing directory with the following
    structure:

        <dataset_directory>/<bug_directory>/annotation/<patch_file>.json

    Each dataset can consist of many BUGs, each BUG should include patch
    of annotated *diff.json file in 'annotation/' subdirectory.
    """
    result = {}
    for dataset in datasets:
        print(f"Dataset {dataset}")
        annotated_bugs = AnnotatedBugDataset(dataset)
        data = annotated_bugs.gather_data_dict(map_diff_to_purpose_dict,
                                               annotations_dir=ctx.obj.annotations_dir)
        result[str(dataset)] = data

    #print(result)
    save_result(result, result_json)


@app.command()
def lines_stats(
    ctx: typer.Context,
    output_file: Annotated[
        Path,
        typer.Argument(
            dir_okay=False,
            help="JSON file to write gathered results to"
        )
    ],
    datasets: Annotated[
        List[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=False,
            help="list of dirs with datasets to process"
        )
    ],
) -> None:
    """Calculate per-bug and per-file count of line types in provided datasets

    Each dataset is expected to be existing directory with the following
    structure:

        <dataset_directory>/<bug_directory>/annotation/<patch_file>.json

    Each dataset can consist of many BUGs, each BUG should include patch
    of annotated *diff.json file in 'annotation/' subdirectory.
    """
    result = {}
    # often there is only one dataset
    for dataset in tqdm.tqdm(datasets, desc='dataset'):
        tqdm.tqdm.write(f"Dataset {dataset}")
        annotated_bugs = AnnotatedBugDataset(dataset)
        data = annotated_bugs.gather_data_dict(map_diff_to_lines_stats,
                                               annotations_dir=ctx.obj.annotations_dir)

        result[str(dataset)] = data

    save_result(result, output_file)


@app.command(help="Gather timeline with per-bug count of lines per type")
def timeline(
    ctx: typer.Context,  # common arguments like --annotations-dir
    output_file: Annotated[
        Path,
        typer.Argument(
            dir_okay=False,
            help="file to write gathered results to"
        )
    ],
    datasets: Annotated[
        List[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=False,
            help="list of dirs with datasets to process"
        )
    ],

) -> None:
    # TODO: extract common part of the command description
    """Calculate timeline of bugs with per-bug count of different types of lines

    For each bug (bugfix commit), compute the count of lines removed and added
    by the patch (commit) in all changed files, keeping separate counts for
    lines with different types, and (separately) with different purposes.

    The gathered data is then saved in a format easy to load into dataframe.

    Each DATASET is expected to be generated by annotating dataset or creating
    annotations from a repository, and should be an existing directory with
    the following structure:

        <dataset_directory>/<bug_directory>/annotation/<patch_file>.json

    Each dataset can consist of many BUGs, each BUG should include JSON
    file with its diff/patch annotations as *.json file in 'annotation/'
    subdirectory (by default).

    Saves gathered timeline results to the OUTPUT_FILE.
    """
    result = {}

    # often there is only one dataset, therefore joblib support is not needed
    for dataset in tqdm.tqdm(datasets, desc='dataset'):
        tqdm.tqdm.write(f"Dataset {dataset}")
        annotated_bugs = AnnotatedBugDataset(dataset)
        data = annotated_bugs.gather_data_list(map_diff_to_timeline,
                                               annotations_dir=ctx.obj.annotations_dir)

        # sanity check
        if not data:
            tqdm.tqdm.write("  warning: no data extracted from this dataset")
        else:
            if 'author.timestamp' not in data[0]:
                tqdm.tqdm.write("  warning: dataset does not include time information")

        result[dataset.name] = data

    # TODO: support other formats than JSON
    save_result(result, output_file)


if __name__ == "__main__":
    app()
