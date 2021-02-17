
import os
import sys
import csv
import json
import glob
import base64
#import tarfile
import zipfile
import sqlite3
import traceback
import itertools
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

import click

from . import db_tool
from .. import settings
from .utils import write_with_size


class ConfigFileNotFoundError(Exception):
    """Raised when language config file with file extention not applied."""
    pass

class ReadReposDirectoryError(Exception):
    """Raised when repos folder not set."""
    pass

def create_zip_file(files_dir):
    """
    Create zip inside snippets folder
    """
    with zipfile.ZipFile(os.path.join(files_dir, '..','snippets.zip'), 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(files_dir):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), os.path.join(files_dir, '..')))



def searching_all_files(directory, extention: str):

    """
    return list of file path inside folder
    """

    file_list = [] # A list for storing files existing in directories
    dir = Path(directory)
    for x in dir.iterdir():
        if x.is_file() and x.name.split('.')[-1] in extention:
           file_list.append(x)
        elif x.name.startswith('.') or x.is_file():
            continue
        else:

           file_list.extend(searching_all_files(dir/x,extention))

    return file_list

def chunk_encode(iterable_lines):
    return base64.b64encode("".join(iterable_lines).encode("utf8")).decode("utf8")


def chunking(repo_path, ext: str, chunksize: int, lines_step: int, common_path):

    """
    Create chunks from given file extemtion and language
    """
    corpus = []

    for source_file in searching_all_files(repo_path, ext):

        try:
                            
            line_number = 0
            with open(source_file, 'r',  encoding='utf8') as file_text:

                file_lines =  file_text.readlines()
                while line_number <= len(file_lines) - 1 - chunksize:
                    corpus.append({"file_name": os.path.relpath(file_text.name, common_path),
                                   "start_line": line_number,
                                   "chunk": "".join(file_lines[line_number: line_number + chunksize])})
                    line_number += lines_step
                
                corpus.append({"file_name": os.path.relpath(file_text.name, common_path),
                               "start_line": line_number,
                               "chunk": "".join(file_lines[line_number:])})
        
        except KeyboardInterrupt:
            raise KeyboardInterrupt('CTRL+C')
        except:
            traceback.print_exc()
            continue
    return corpus



@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--crawldir', '-d', default='.', help='Snippets output filder.', show_default=True)
@click.option('--languages-dir', '-L', help='Path to directory with languages repos.')
@click.option('--chunksize', '-c', type=int, default=10, help='Size of code snippet.')
@click.option('--rows-step', '-r', type=int, default=None, help='Distance between start rows.')
@click.option('--sqlite-path', '-q', help='Sqlite for writing snippets.', default = None,  show_default=True)
@click.option('--languages-file', '-f', default=None, help='Path to json file with languages for extracting.')
def generate_datasets(crawldir: str, languages_dir: Optional[str], chunksize: int, sqlite_path: Optional[str], rows_step: Optional[int], languages_file: str):
    
    """
    Create snippets dataset from cloned repos
    """

    if not rows_step:
        rows_step = chunksize

    if not languages_dir:
        languages_dir = os.environ.get('LANGUAGES_REPOS')
        if not languages_dir:
            raise ReadReposDirectoryError('LANGUAGES_REPOS not set.')


    

    

    # Read languages config file
    try:
        if not languages_file:
            if not os.path.exists( Path(languages_dir) / "languages_config.json" ):
                raise ConfigFileNotFoundError('Config file not found.')
            else:
                langs_file = Path(languages_dir) / "languages_config.json"
        else:

            langs_file = Path(languages_file)
        with langs_file.open('r', encoding='utf8') as langs:
            languages_ext = json.load(langs)
    except Exception as err:
        print(f"Can't read languages file. Err: {err}")
        raise
    
    

    # Create separate folder

    snippets_dir = os.path.join(crawldir, "snippets")

    if not os.path.exists(snippets_dir):
        os.makedirs(snippets_dir)

    # Create connection
    conn = db_tool.create_connection(os.path.join(snippets_dir,"snippets.db"))
    db_tool.create_snippets_table(conn)

    for lang in languages_ext:

        lang_path = os.path.join(languages_dir, lang)

        meta_path =  os.path.join(lang_path, "meta.json")

        with open(meta_path, 'r') as repos_meta_file:
            repos_meta = json.load(repos_meta_file)


        for repo in repos_meta["repos"]:
            license = None

            if repo['license']:
                license =  repo['license']['spdx_id']
            

            language_chunks = chunking(os.path.join(lang_path,repo['name']),
                                    languages_ext[lang],
                                    chunksize,
                                    rows_step,
                                    languages_dir)


            if not language_chunks:
                continue
            
            for chunk_data in language_chunks:

                try:
                    
                    db_tool.write_snippet_to_db(conn, **{ 'github_repo_url': repo["github_repo_url"],
                                                          'commit_hash': repo['commit_hash'],
                                                          'snippet': chunk_data["chunk"],
                                                          'license': license,
                                                          'language': lang.lower(),
                                                          "repo_file_name": str(Path(chunk_data["file_name"])),
                                                          "starting_line_number": chunk_data["start_line"]})

                
                except KeyboardInterrupt:
                    raise KeyboardInterrupt('CTRL+C')

                except Exception as err:
                    print(err)
                    raise

    create_zip_file(snippets_dir)
    
    with open(Path(snippets_dir)/ '..' / f"meta.json", 'w') as meta_out:
        # chunksize: int, sqlite_path: Optional[str], rows_step: Optional[int]
        json.dump({"mirror version" : settings.module_version,
                         "date": f"{datetime.now()}",
                         "languages init config": languages_ext,
                         "chunksize": chunksize,
                         "rows_step": rows_step}, meta_out)




if __name__ == "__main__":
    generate_datasets()
