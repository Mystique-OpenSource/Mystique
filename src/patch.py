from __future__ import annotations

import logging
from pathlib import Path

from pydriller import GitRepository, Modification
from pydriller.domain.commit import Commit, ModificationType
from pydriller.utils.conf import Conf

import difftools
import format
from codefile import CodeFile
from common import Language
from project import Class, Field, File, Import, Method, Project


class BPCommit(Commit):
    def _get_decoded_sc_str(self, diff):
        try:
            return diff.data_stream.read().decode('utf-8', 'ignore')
        except (UnicodeDecodeError, AttributeError, ValueError):
            logging.debug('Could not load source code of a '
                          'file in commit %s', self._c_object.hexsha)
            return None


class Patch:
    def __init__(self, repo_path: str, commit_id: str, language: Language):
        self.repo_path = repo_path
        self.repo_name = repo_path.split("/")[-1]
        self.commit_id = commit_id
        path = Path(repo_path).expanduser().resolve()
        conf = Conf({"path_to_repo": str(path),
                     'skip_whitespaces': True,
                     'include_remotes': True})
        self.repo = GitRepository(repo_path, conf=conf)
        self.commit = self.repo.get_commit(commit_id)
        # self.bpcommit = BPCommit(self.commit._c_object, self.commit._conf)
        # self.bpdiffs = self.bpcommit.modifications

        self.diffs: list[Modification] = self.commit.modifications

        self.modify_files: list[Modification] = []
        self.add_files: list[Modification] = []
        self.del_files: list[Modification] = []
        for file in self.diffs:
            if not Patch.is_patch_related_file(file, language):
                continue
            if file.change_type == ModificationType.ADD:
                self.add_files.append(file)
            elif file.change_type == ModificationType.DELETE:
                self.del_files.append(file)
            elif file.change_type == ModificationType.MODIFY:
                source_code_before = format.format(file.source_code_before, language,
                                                   del_comment=True, del_linebreak=True)
                source_code = format.format(file.source_code, language, del_comment=True, del_linebreak=True)
                diff_and_sc = {
                    "diff": difftools.git_diff_code(source_code_before, source_code, remove_diff_header=True),
                    "source_code_before": source_code_before,
                    "source_code": source_code
                }
                modification = Modification(file.old_path, file.new_path, file.change_type, diff_and_sc)
                self.modify_files.append(modification)

        self.pre_project = Project("1.pre", self.pre_modify_files, language)
        self.post_project = Project("2.post", self.post_modify_files, language)

    @property
    def added_files(self) -> list[File]:
        file_name_list = self.post_project.files_path_set - self.pre_project.files_path_set
        file_list = []
        for file_name in file_name_list:
            file = self.post_project.get_file(file_name)
            if file is not None:
                file_list.append(file)
        return file_list

    @property
    def deleted_files(self) -> list[File]:
        file_name_list = self.pre_project.files_path_set - self.post_project.files_path_set
        file_list = []
        for file_name in file_name_list:
            file = self.post_project.get_file(file_name)
            if file is not None:
                file_list.append(file)
        return file_list

    @property
    def added_imports(self) -> list[Import]:
        import_name_list = self.post_project.imports_signature_set - self.pre_project.imports_signature_set
        import_list = []
        for import_name in import_name_list:
            import_ = self.post_project.get_import(import_name)
            if import_ is not None:
                import_list.append(import_)
        return import_list

    @property
    def deleted_imports(self) -> list[Import]:
        import_name_list = self.pre_project.imports_signature_set - self.post_project.imports_signature_set
        import_list = []
        for import_name in import_name_list:
            import_ = self.post_project.get_import(import_name)
            if import_ is not None:
                import_list.append(import_)
        return import_list

    @property
    def added_classes(self) -> list[Class]:
        class_name_list = self.post_project.classes_signature_set - self.pre_project.classes_signature_set
        class_list = []
        for class_name in class_name_list:
            clazz = self.post_project.get_class(class_name)
            if clazz is not None:
                class_list.append(clazz)
        return class_list

    @property
    def deleted_classes(self) -> list[Class]:
        class_name_list = self.pre_project.classes_signature_set - self.post_project.classes_signature_set
        class_list = []
        for class_name in class_name_list:
            clazz = self.post_project.get_class(class_name)
            if clazz is not None:
                class_list.append(clazz)
        return class_list

    @property
    def added_methods(self) -> list[Method]:
        method_name_list = self.post_project.methods_signature_set - self.pre_project.methods_signature_set
        method_list = []
        for method_name in method_name_list:
            method = self.post_project.get_method(method_name)
            if method is not None:
                method_list.append(method)
        return method_list

    @property
    def deleted_methods(self) -> list[Method]:
        method_name_list = self.pre_project.methods_signature_set - self.post_project.methods_signature_set
        method_list = []
        for method_name in method_name_list:
            method = self.post_project.get_method(method_name)
            if method is not None:
                method_list.append(method)
        return method_list

    @property
    def added_methods_signature_set(self) -> set[str]:
        return self.post_project.methods_signature_set - self.pre_project.methods_signature_set

    @property
    def deleted_methods_signature_set(self) -> set[str]:
        return self.pre_project.methods_signature_set - self.post_project.methods_signature_set

    @property
    def added_fields(self) -> list[Field]:
        field_name_list = self.post_project.fields_signature_set - self.pre_project.fields_signature_set
        field_list = []
        for field_name in field_name_list:
            field = self.post_project.get_field(field_name)
            if field is not None:
                field_list.append(field)
        return field_list

    @property
    def deleted_fields(self) -> list[Field]:
        field_name_list = self.pre_project.fields_signature_set - self.post_project.fields_signature_set
        field_list = []
        for field_name in field_name_list:
            field = self.post_project.get_field(field_name)
            if field is not None:
                field_list.append(field)
        return field_list

    @property
    def changed_files(self) -> list[File]:
        file_path_list = []
        for file in self.modify_files:
            file_path_list.append(file.new_path)
        file_list = []
        for file_name in file_path_list:
            file = self.post_project.get_file(file_name)
            if file is not None:
                file_list.append(file)
        return file_list

    @property
    def changed_files_path_set(self) -> set[str]:
        file_path_list = []
        for file in self.modify_files:
            file_path_list.append(file.new_path)
        return set(file_path_list)

    @property
    def avarage_method_change(self) -> float:
        changed_methods = self.changed_methods
        total_lines = 0
        for method_sig in changed_methods:
            pre_method = self.pre_project.get_method(method_sig)
            post_method = self.post_project.get_method(method_sig)
            if pre_method is None or post_method is None:
                continue
            changed_lines = len(pre_method.diff_lines)
            total_lines += changed_lines
        if len(changed_methods) == 0:
            return 0
        return total_lines / len(changed_methods)

    @property
    def changed_methods(self) -> set[str]:
        changed_methods: set[str] = set()
        for file in self.modify_files:
            path = file.new_path
            if path is None:
                continue
            pre_file = self.pre_project.get_file(path)
            post_file = self.post_project.get_file(path)
            if pre_file is None:
                continue
            if post_file is None:
                continue
            add_lines = set([line[0] for line in file.diff_parsed["added"]])
            delete_lines = set([line[0] for line in file.diff_parsed["deleted"]])
            for method in pre_file.methods:
                if method.signature in self.added_methods_signature_set | self.deleted_methods_signature_set:
                    continue
                method_line_set = set(range(method.body_start_line, method.body_end_line + 1))
                method_deleted_lines = method_line_set & delete_lines
                if method_deleted_lines:
                    changed_methods.add(method.signature)
            for method in post_file.methods:
                if method.signature in self.added_methods_signature_set | self.deleted_methods_signature_set:
                    continue
                method_line_set = set(range(method.body_start_line, method.body_end_line + 1))
                method_added_lines = method_line_set & add_lines  # 方法内部新增的行号
                if method_added_lines:
                    changed_methods.add(method.signature)

        for method in changed_methods.copy():
            pre_method = self.pre_project.get_method(method)
            post_method = self.post_project.get_method(method)
            if pre_method is None or post_method is None:
                continue
            if pre_method.normalized_body_code == post_method.normalized_body_code:
                changed_methods.remove(method)
            pre_method.counterpart = post_method
            post_method.counterpart = pre_method
        return changed_methods

    @property
    def pre_modify_files(self) -> list[CodeFile]:
        result = []
        for file in self.modify_files:
            assert file.new_path is not None
            file = CodeFile(file.new_path, file.source_code_before)
            result.append(file)
        for file in self.del_files:
            assert file.old_path is not None
            file = CodeFile(file.old_path, file.source_code_before)
            result.append(file)
        return result

    @property
    def post_modify_files(self) -> list[CodeFile]:
        result = []
        for file in self.modify_files:
            assert file.new_path is not None
            file = CodeFile(file.new_path, file.source_code)
            result.append(file)
        for file in self.add_files:
            assert file.new_path is not None
            file = CodeFile(file.new_path, file.source_code)
            result.append(file)
        return result

    @staticmethod
    def is_patch_related_file(file: str | Modification, language: Language) -> bool:
        if language == Language.JAVA:
            extension = ["java"]
        else:
            extension = ["c","cc","cxx","cpp","c++","h"]
        if isinstance(file, str):
            return file.split(".")[-1] in extension and "test/" not in file
        if isinstance(file, Modification):
            if file.filename.split(".")[-1] not in extension:
                return False
            if file.change_type == ModificationType.MODIFY and file.new_path is not None:
                file_path = file.new_path
            elif file.change_type == ModificationType.ADD and file.new_path is not None:
                file_path = file.new_path
            elif file.change_type == ModificationType.DELETE and file.old_path is not None:
                file_path = file.old_path
            else:
                return False
            return "test/" not in file_path and "tests/" not in file_path
