import os

import format
from common import Language


class CodeFile:
    def __init__(self, file_path: str, code: str):
        self.file_path = file_path
        self.code = code
        self.language = Language.JAVA if file_path.endswith(".java") else Language.C

    @property
    def formated_code(self):
        return format.format(self.code, self.language, del_comment=True, del_linebreak=True)

def create_file_tree(code_files: list[CodeFile], code_dir: str, overwrite: bool = False):
    if os.path.exists(code_dir) and not overwrite:
        return code_dir
    os.makedirs(code_dir, exist_ok=True)

    for file in code_files:
        code = file.formated_code
        path = file.file_path
        assert path is not None
        os.makedirs(os.path.dirname(os.path.join(code_dir, path)), exist_ok=True)
        with open(os.path.join(code_dir, path), "w") as f:
            f.write(code)
    return code_dir

def create_code_tree(code_files: list[CodeFile], dir: str, overwrite: bool = True) -> str:
    code_dir = os.path.join(dir, "code")
    create_file_tree(code_files, code_dir, overwrite)
    return code_dir
    

def create_callgraph_tree(code_files: list[CodeFile], dir: str, overwrite: bool = True):
    code_dir = os.path.join(dir, "analysis")
    
    create_file_tree(code_files, code_dir, overwrite)
    return code_dir