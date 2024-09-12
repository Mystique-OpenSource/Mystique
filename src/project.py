from __future__ import annotations

import ast
import hashlib
import itertools
import os
import sys
from collections import deque
from functools import cached_property

import ast_parser
import format
import joern
import networkx as nx
import utils
from ast_parser import ASTParser
from codefile import CodeFile
from common import Language
from difftools import AddHunk, DelHunk, Hunk, ModHunk, get_patch_hunks
from joern import PDGNode
from tree_sitter import Node


class ProjectJoern:
    def __init__(self, cpg_dir: str, pdg_dir: str):
        self.cpg = joern.CPG(cpg_dir)
        self.pdgs: dict[tuple[int, str, str], joern.PDG] = self.build_pdgs(pdg_dir)
        self.path = cpg_dir.replace("/cpg", "")

    def build_pdgs(self, pdg_dir: str):
        dot_names = os.listdir(pdg_dir)
        pdgs: dict[tuple[int, str, str], joern.PDG] = {}
        for dot in dot_names:
            dot_path = os.path.join(pdg_dir, dot)
            try:
                pdg = joern.PDG(pdg_path=dot_path)
            except Exception as e:
                continue
            if pdg.name is None:
                continue
            if pdg.line_number is None or pdg.filename is None:
                continue
            pdgs[(pdg.line_number, pdg.name, pdg.filename)] = pdg
        return pdgs

    def get_pdg(self, method: Method) -> joern.PDG | None:
        if method.clazz is not None and method.name == method.clazz.name:
            return self.pdgs.get((method.start_line, "<init>", method.file.path))
        else:
            return self.pdgs.get((method.start_line, method.name, method.file.path))


class Project:
    def __init__(self, project_name: str, files: list[CodeFile], language: Language):
        self.project_name = project_name
        self.language = language
        self.files: list[File] = []

        self.files_path_set: set[str] = set()
        self.imports_signature_set: set[str] = set()
        self.classes_signature_set: set[str] = set()
        self.methods_signature_set: set[str] = set()
        self.fields_signature_set: set[str] = set()

        for file in files:
            file = File(file.file_path, file.formated_code, self, language)
            self.files.append(file)
            self.files_path_set.add(file.path)
            if language == Language.JAVA:
                self.imports_signature_set.update([import_.signature for import_ in file.imports])
                self.classes_signature_set.update([clazz.fullname for clazz in file.classes])
                self.methods_signature_set.update(
                    [method.signature for clazz in file.classes for method in clazz.methods])
                self.fields_signature_set.update([field.signature for clazz in file.classes for field in clazz.fields])
            elif language == Language.C:
                self.imports_signature_set.update([import_.signature for import_ in file.imports])
                self.methods_signature_set.update([method.signature for method in file.methods])

        self.joern: ProjectJoern | None = None

    def load_joern_graph(self, cpg_dir: str, pdg_dir: str):
        self.joern = ProjectJoern(cpg_dir, pdg_dir)

    def get_file(self, path: str) -> File | None:
        for file in self.files:
            if file.path == path:
                return file
        return None

    def get_import(self, signature: str) -> Import | None:
        for file in self.files:
            for import_ in file.imports:
                if import_.signature == signature:
                    return import_
        return None

    def get_class(self, fullname: str) -> Class | None:
        for file in self.files:
            for clazz in file.classes:
                if clazz.fullname == fullname:
                    return clazz
        return None

    def get_method(self, fullname: str) -> Method | None:
        if self.language == Language.JAVA:
            for file in self.files:
                for clazz in file.classes:
                    for method in clazz.methods:
                        if method.signature == fullname:
                            return method
        elif self.language == Language.C:
            for file in self.files:
                for method in file.methods:
                    if method.signature == fullname:
                        return method
        return None

    def get_only_method(self) -> Method | None:
        if self.language == Language.C:
            if len(self.files) == 1 and len(self.files[0].methods) == 1:
                return self.files[0].methods[0]
        return None

    def get_field(self, fullname: str) -> Field | None:
        for file in self.files:
            for clazz in file.classes:
                for field in clazz.fields:
                    if field.signature == fullname:
                        return field
        return None

    @staticmethod
    def get_triple_methods(triple_projects: tuple[Project, Project, Project], signature: str):
        pre_project, post_project, target_project = triple_projects
        pre_method = pre_project.get_method(signature)
        post_method = post_project.get_method(signature)
        target_method = target_project.get_method(signature)
        if pre_method is not None and post_method is None:
            post_method = post_project.get_only_method()
        if pre_method is None:
            return
        if post_method is None:
            return
        if target_method is None:
            return
        return pre_method, post_method, target_method

    @staticmethod
    def get_triple_methods_java(triple_projects: tuple[Project, Project, Project], triple_signature: tuple[str, str, str]):
        pre_project, post_project, target_project = triple_projects
        pre_signature, post_signature, target_signature = triple_signature
        pre_method = pre_project.get_method(pre_signature)
        post_method = post_project.get_method(post_signature)
        target_method = target_project.get_method(target_signature)
        if pre_method is not None and post_method is None:
            post_method = post_project.get_only_method()
        if pre_method is None:
            return
        if post_method is None:
            return
        if target_method is None:
            return
        return pre_method, post_method, target_method


class File:
    def __init__(self, path: str, content: str, project: Project | None, language: Language):
        self.language = language
        parser = ASTParser(content, language)
        self.parser = parser
        self.path = path
        self.name = os.path.basename(path)
        self.code = content
        if project is None:
            self.project = Project("None", [CodeFile(path, content)], language)
        else:
            self.project = project

    @cached_property
    def package(self) -> str:
        assert self.language == Language.JAVA
        package_node = self.parser.query_oneshot(ast_parser.TS_JAVA_PACKAGE)
        return package_node.text.decode() if package_node is not None else "<NONE>"

    @cached_property
    def imports(self) -> list[Import]:
        if self.language == Language.JAVA:
            return [Import(import_node[0], self, self.language) for import_node in self.parser.query(ast_parser.TS_JAVA_IMPORT)]
        elif self.language == Language.C:
            return [Import(import_node[0], self, self.language) for import_node in self.parser.query(ast_parser.TS_C_INCLUDE)]
        else:
            return []

    @cached_property
    def classes(self) -> list[Class]:
        if self.language == Language.JAVA:
            return [Class(class_node[0], self, self.language)
                    for class_node in self.parser.query(ast_parser.TS_JAVA_CLASS)]
        else:
            return []

    @cached_property
    def fields(self) -> list[Field]:
        return [field for clazz in self.classes for field in clazz.fields]

    @cached_property
    def methods(self) -> list[Method]:
        if self.language == Language.JAVA:
            return [method for clazz in self.classes for method in clazz.methods]
        elif self.language == Language.C:
            methods: list[Method] = []
            query = ast_parser.TS_C_METHOD
            for method_node in self.parser.query(query):
                methods.append(Method(method_node[0], None, self, self.language))
            return methods
        else:
            return []


class Import:
    def __init__(self, node: Node, file: File, language: Language):
        self.file = file
        self.node = node
        self.code = node.text.decode()
        self.signature = file.path + "#" + self.code


class Class:
    def __init__(self, node: Node, file: File, language: Language):
        self.language = language
        self.file = file
        self.code = node.text.decode()
        self.node = node
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        self.name = name_node.text.decode()
        self.fullname = f"{file.package}.{self.name}"

    @cached_property
    def fields(self):
        file = self.file
        parser = file.parser
        class_node = self.node
        class_name = self.name
        fields: list[Field] = []
        query = f"""
        (class_declaration
            name: (identifier)@class.name
            (#eq? @class.name "{class_name}")
            body: (class_body
                (field_declaration)@field
            )
        )
        """
        for field_node in parser.query_from_node(class_node, query):
            if field_node[1] != "field":
                continue
            fields.append(Field(field_node[0], self, file))
        return fields

    @cached_property
    def methods(self):
        file = self.file
        parser = file.parser
        class_node = self.node
        class_name = self.name
        methods: list[Method] = []
        query = f"""
        (class_declaration
            name: (identifier)@class.name
            (#eq? @class.name "{class_name}")
            body: (class_body
                [(method_declaration)
                (constructor_declaration)]@method
            )
        )
        """
        for method_node in parser.query_from_node(class_node, query):
            if method_node[1] != "method":
                continue
            methods.append(Method(method_node[0], self, file, self.language))
        return methods


class Field:
    def __init__(self, node: Node, clazz: Class, file: File):
        self.name = node.child_by_field_name("declarator").child_by_field_name("name").text.decode()  # type: ignore
        self.clazz = clazz
        self.file = file
        self.code = node.text.decode()  # type: ignore
        self.signature = f"{self.clazz.fullname}.{self.name}"


class Method:
    def __init__(self, node: Node, clazz: Class | None, file: File, language: Language):
        self.language = language
        if language == Language.JAVA:
            name_node = node.child_by_field_name("name")
            assert name_node is not None
            assert name_node.text is not None
            self.name = name_node.text.decode()
        else:
            name_node = node.child_by_field_name("declarator")
            while name_node is not None and name_node.type not in {"identifier", "operator_name", "type_identifier"}:
                all_temp_name_node = name_node
                if name_node.child_by_field_name("declarator") is None and name_node.type == "reference_declarator":
                    for temp_node in name_node.children:
                        if temp_node.type == "function_declarator":
                            name_node = temp_node
                            break
                if name_node.child_by_field_name("declarator") is not None:
                    name_node = name_node.child_by_field_name("declarator")
                while name_node is not None and (name_node.type == "qualified_identifier" or name_node.type == "template_function"):
                    temp_name_node = name_node
                    for temp_node in name_node.children:
                        if temp_node.type in {"identifier", "destructor_name", "qualified_identifier", "operator_name", "type_identifier", "pointer_type_declarator"}:
                            name_node = temp_node
                            break
                    if name_node == temp_name_node:
                        break
                if name_node is not None and name_node.type == "destructor_name":
                    for temp_node in name_node.children:
                        if temp_node.type == "identifier":
                            name_node = temp_node
                            break

                if name_node is not None and name_node.type == "field_identifier" and name_node.child_by_field_name("declarator") is None:
                    break
                if name_node == all_temp_name_node:
                    break
            assert name_node is not None
            assert name_node.text is not None
            self.name = name_node.text.decode()
        self.clazz = clazz
        self.file = file
        self.node = node
        assert node.text is not None
        self.code = node.text.decode()
        self.start_line = node.start_point[0] + 1
        self.end_line = node.end_point[0] + 1

        self.lines: dict[int, str] = {i + self.start_line: line for i, line in enumerate(self.code.split("\n"))}

        self._pdg: joern.PDG | None = None
        self.counterpart: Method | None = None
        self.method_dir: str | None = None

    @classmethod
    def init_from_file_code(cls, path: str, language: Language):
        with open(path, "r") as f:
            code = f.read()
        file = File(path, code, None, language)
        parser = ASTParser(code, language)
        method_node = parser.query_oneshot(ast_parser.TS_C_METHOD)
        assert method_node is not None
        return cls(method_node, None, file, language)

    @classmethod
    def init_from_code(cls, code: str, language: Language):
        file = File("None", code, None, language)
        parser = ASTParser(code, language)
        if language == Language.C:
            method_node = parser.query_oneshot(ast_parser.TS_C_METHOD)
        else:
            method_node = parser.query_oneshot(ast_parser.TS_JAVA_METHOD)
        if method_node is None:
            return None
        return cls(method_node, None, file, language)

    @staticmethod
    def init_method_dir(triple_methods: tuple[Method, Method, Method], cache_dir: str, slice_level: int, fixed_method: Method | None = None) -> str:
        pre_method, post_method, target_method = triple_methods
        method_dir = f"{cache_dir}/method#{slice_level}/{pre_method.signature_r}"
        if len(method_dir) > 30:
            file_path_md5 = hashlib.md5(pre_method.name.encode()).hexdigest()[:4]
            method_dir = f"{cache_dir}/method#{slice_level}/{pre_method.name}#{file_path_md5}"
        dot_dir = os.path.join(method_dir, "dot")
        diff_dir = os.path.join(method_dir, "diff")
        os.makedirs(method_dir, exist_ok=True)
        os.makedirs(dot_dir, exist_ok=True)
        os.makedirs(diff_dir, exist_ok=True)
        pre_method.method_dir, post_method.method_dir, target_method.method_dir = (method_dir,) * 3

        pre_method.write_code(method_dir)
        post_method.write_code(method_dir)
        target_method.write_code(method_dir)

        pre_method.write_dot(dot_dir)
        post_method.write_dot(dot_dir)
        target_method.write_dot(dot_dir)

        if fixed_method is not None:
            fixed_method.method_dir = method_dir
            fixed_method.write_code(method_dir)
        return method_dir

    @property
    def pdg(self) -> joern.PDG | None:
        assert self.file.project.joern is not None
        if self._pdg is None:
            self._pdg = self.file.project.joern.get_pdg(self)
        return self._pdg

    @property
    def line_pdg_pairs(self) -> dict[int, joern.PDGNode] | None:
        line_pdg_pairs = {}
        if self.pdg is None:
            return None
        for node_id in self.pdg.g.nodes():
            node = self.pdg.get_node(node_id)
            if node.line_number is None:
                continue
            line_pdg_pairs[node.line_number] = node
        return line_pdg_pairs

    @property
    def rel_line_pdg_pairs(self) -> dict[int, joern.PDGNode] | None:
        rel_line_pdg_pairs = {}
        if self.pdg is None:
            return None
        for node_id in self.pdg.g.nodes():
            node = self.pdg.get_node(node_id)
            if node.line_number is None:
                continue
            rel_line_pdg_pairs[node.line_number - self.start_line + 1] = node
        return rel_line_pdg_pairs

    @property
    def body_node(self) -> Node | None:
        return self.node.child_by_field_name("body")

    @property
    def body_start_line(self) -> int:
        if self.body_node is None:
            return self.start_line
        else:
            return self.body_node.start_point[0] + 1

    @property
    def body_end_line(self) -> int:
        if self.body_node is None:
            return self.end_line
        else:
            return self.body_node.end_point[0] + 1

    @property
    def diff_dir(self) -> str:
        assert self.method_dir is not None
        return f"{self.method_dir}/diff"

    @property
    def dot_dir(self) -> str:
        assert self.method_dir is not None
        return f"{self.method_dir}/dot"

    @property
    def rel_line_set(self) -> set[int]:
        return set(range(self.rel_start_line, self.rel_end_line + 1))

    @property
    def return_type(self) -> str:
        if self.language == Language.C or self.language == Language.JAVA:
            type_node = self.node.child_by_field_name("type")
            if type_node is not None:
                assert type_node.text is not None
                return type_node.text.decode()
        return ""

    @property
    def parameter_signature(self) -> str:
        parameter_signature_list = []
        for param in self.parameters:
            type_node = param.child_by_field_name("type")
            assert type_node is not None
            if type_node.type == "generic_type":
                type_identifier_node = ASTParser.child_by_type_name(type_node, "type_identifier")
                if type_identifier_node is None:
                    type_name = ""
                else:
                    assert type_identifier_node.text is not None
                    type_name = type_identifier_node.text.decode()
            else:
                assert type_node.text is not None
                type_name = type_node.text.decode()
            parameter_signature_list.append(type_name)
        return ",".join(parameter_signature_list)

    @property
    def signature(self) -> str:
        if self.language == Language.JAVA:
            assert self.clazz is not None
            return f"{self.clazz.fullname}.{self.name}({self.parameter_signature})"
        else:
            return f"{self.file.name}#{self.name}"

    @property
    def signature_r(self) -> str:
        if self.language == Language.JAVA:
            assert self.clazz is not None
            fullname_r = ".".join(self.clazz.fullname.split(".")[::-1])
            return f"{self.name}({self.parameter_signature}).{fullname_r}"
        else:
            return f"{self.name}#{self.start_line}#{self.end_line}#{self.file.name}"

    @property
    def parameters(self) -> list[Node]:
        parameters = []
        if self.language == Language.JAVA:
            parameters_node = self.node.child_by_field_name("parameters")
            if parameters_node is None:
                return []
            parameters = ASTParser.children_by_type_name(parameters_node, "formal_parameter")
        elif self.language == Language.C:
            func_declarator = ASTParser.children_by_type_name(self.node, "function_declarator")
            if len(func_declarator) == 0:
                func_declarator = self.node.child_by_field_name("declarator")
                while func_declarator is not None and func_declarator.type != "function_declarator":
                    func_declarator = func_declarator.child_by_field_name("declarator")
            else:
                func_declarator = func_declarator[0]
            if func_declarator is None:
                print(f"{self.signature} not found")
                return []
            parameters_node = func_declarator.child_by_field_name("parameters")
            if parameters_node is None:
                return []
            parameters = ASTParser.children_by_type_name(parameters_node, "parameter_declaration")
        return parameters

    @property
    def diff_lines(self) -> set[int]:
        lines = set()
        for hunk in self.patch_hunks:
            if isinstance(hunk, DelHunk):
                lines.update(range(hunk.a_startline, hunk.a_endline + 1))
            elif isinstance(hunk, ModHunk):
                lines.update(range(hunk.a_startline, hunk.a_endline + 1))
        return lines

    @property
    def rel_diff_lines(self) -> set[int]:
        return set([line - self.start_line + 1 for line in self.diff_lines])

    @property
    def diff_identifiers(self) -> dict[int, set[str]]:
        assert self.counterpart is not None
        diff_identifiers = {}
        for hunk in self.patch_hunks:
            if isinstance(hunk, DelHunk):
                lines = set(range(hunk.a_startline, hunk.a_endline + 1))
                criteria_identifier_a = self.identifier_by_lines(lines)
                diff_identifiers.update(criteria_identifier_a)
            elif isinstance(hunk, ModHunk):
                a_lines = set(range(hunk.a_startline, hunk.a_endline + 1))
                b_lines = set(range(hunk.b_startline, hunk.b_endline + 1))
                criteria_identifier_a = self.identifier_by_lines(a_lines)
                criteria_identifier_b = self.counterpart.identifier_by_lines(b_lines)
                lines = a_lines.union(b_lines)
                for line in lines:
                    if line in criteria_identifier_a.keys() and line in criteria_identifier_b.keys():
                        diff_identifiers[line] = criteria_identifier_a[line] - criteria_identifier_b[line]
                    elif line in criteria_identifier_a.keys():
                        diff_identifiers[line] = criteria_identifier_a[line]
        return diff_identifiers

    @cached_property
    def patch_hunks(self) -> list[Hunk]:
        assert self.counterpart is not None
        hunks = get_patch_hunks(self.file.code, self.counterpart.file.code)
        for hunk in hunks.copy():
            if isinstance(hunk, ModHunk) or isinstance(hunk, DelHunk):
                if not (self.start_line <= hunk.a_startline and hunk.a_endline <= self.end_line):
                    hunks.remove(hunk)
            elif isinstance(hunk, AddHunk):
                if hunk.insert_line < self.start_line or hunk.insert_line > self.end_line:
                    hunks.remove(hunk)

        def sort_key(hunk: Hunk):
            if isinstance(hunk, AddHunk):
                return hunk.insert_line
            elif isinstance(hunk, ModHunk) or isinstance(hunk, DelHunk):
                return hunk.a_startline
            else:
                return 0
        hunks.sort(key=sort_key)
        return hunks

    @property
    def header_lines(self) -> set[int]:
        return set(range(self.start_line, self.body_start_line + 1))

    @property
    def body_lines(self) -> set[int]:
        body_start_line = self.body_start_line
        body_end_line = self.body_end_line
        if self.lines[self.body_start_line].strip().endswith("{"):
            body_start_line += 1
        if self.lines[self.body_end_line].strip().endswith("}"):
            body_end_line -= 1
        return set(range(body_start_line, body_end_line + 1))

    @property
    def body_code(self) -> str:
        return "\n".join([self.lines[line] for line in sorted(self.body_lines)])

    @property
    def comment_lines(self) -> set[int]:
        body_node = self.node.child_by_field_name("body")
        if body_node is None:
            return set()
        comment_lines = set()
        query = """
        (line_comment)@line_comment
        (block_comment)@block_comment
        """
        comment_nodes = self.file.parser.query_from_node(body_node, query)
        line_comments = [comment[0] for comment in comment_nodes if comment[1] == "line_comment"]
        block_comments = [comment[0] for comment in comment_nodes if comment[1] == "block_comment"]
        for comment_node in line_comments:
            line = comment_node.start_point[0] + 1
            if self.lines[line].strip() == comment_node.text.decode().strip():  # type: ignore
                comment_lines.add(line)
        for comment_node in block_comments:
            start_line = comment_node.start_point[0] + 1
            end_line = comment_node.end_point[0] + 1
            if self.lines[start_line].strip().startswith("/*"):
                comment_lines.update(range(start_line, end_line + 1))
        return comment_lines

    def code_by_lines(self, lines: set[int], *, placeholder: str | None = None) -> str:
        if placeholder is None:
            result = "\n".join([self.rel_lines[line] for line in sorted(lines)])
            return result + "\n"
        else:
            code_with_placeholder = ""
            last_line = 0
            placeholder_counter = 0
            for line in sorted(lines):
                if line - last_line > 1:
                    is_comment = True
                    for i in range(last_line + 1, line):
                        if self.rel_lines[i].strip() == "":
                            continue
                        if not self.rel_lines[i].strip().startswith("//"):
                            is_comment = False
                            break
                    if is_comment:
                        pass
                    elif line - last_line == 2 and (self.rel_lines[line - 1].strip() == "" or self.rel_lines[line - 1].strip().startswith("//")):
                        pass
                    else:
                        code_with_placeholder += f"{placeholder}\n"
                        placeholder_counter += 1
                code_with_placeholder += self.rel_lines[line] + "\n"
                last_line = line
            return code_with_placeholder

    def reduced_hunks(self, slines: set[int]) -> list[str]:
        placeholder_lines = self.rel_line_set - slines
        return self.code_hunks(placeholder_lines)

    def code_hunks(self, lines: set[int]) -> list[str]:
        hunks: list[str] = []
        lineg = utils.group_consecutive_ints(list(lines))
        for g in lineg:
            hunk = self.code_by_lines(set(g))
            hunks.append(hunk)
        return hunks

    def recover_placeholder(self, code: str, slice_lines: set[int], placeholder: str) -> str | None:
        placeholder_hunks = self.reduced_hunks(slice_lines)
        if code.count(placeholder) != len(placeholder_hunks):
            return None
        result = ""
        for line in code.split("\n"):
            if line.strip().lower() == placeholder.strip().lower():
                result += placeholder_hunks.pop(0)
            else:
                result += line + "\n"
        return result

    def code_by_exclude_lines(self, lines: set[int], *, placeholder: str | None) -> str:
        exclude_lines = self.rel_line_set - lines
        return self.code_by_lines(exclude_lines, placeholder=placeholder)

    def identifier_by_lines(self, lines: set[int]) -> dict[int, set[str]]:
        identifiers: dict[int, set[str]] = {}
        if self.language == Language.C:
            identifier_nodes = self.file.parser.get_all_identifier_node()
            for node in identifier_nodes:
                if node.parent is not None and node.parent.type == "unary_expression":
                    line = node.parent.start_point[0] + 1
                    if line in lines:
                        assert node.parent.text is not None
                        node_text = node.parent.text.decode()
                        try:
                            identifiers[line].add(node_text)
                        except KeyError:
                            identifiers[line] = {node_text}
                else:
                    line = node.start_point[0] + 1
                    if line in lines:
                        assert node.text is not None
                        node_text = node.text.decode()
                        try:
                            identifiers[line].add(node_text)
                        except KeyError:
                            identifiers[line] = {node_text}
        return identifiers

    @property
    def normalized_body_code(self) -> str:
        return format.normalize(self.body_code)

    @property
    def formatted_code(self) -> str:
        return format.format(self.code, self.language, del_comment=True, del_linebreak=True)

    @property
    def rel_start_line(self) -> int:
        return 1

    @property
    def rel_end_line(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def rel_body_start_line(self) -> int:
        return self.body_start_line - self.start_line + 1

    @property
    def rel_body_end_line(self) -> int:
        return self.body_end_line - self.start_line + 1

    @property
    def rel_lines(self) -> dict[int, str]:
        return {line - self.start_line + 1: code for line, code in self.lines.items()}

    @property
    def length(self):
        return self.end_line - self.start_line + 1

    @property
    def file_suffix(self):
        if self.language == Language.C:
            suffix = ".c"
        elif self.language == Language.JAVA:
            suffix = ".java"
        else:
            suffix = ""
        return suffix

    def write_dot(self, dir: str | None = None):
        assert self.pdg is not None
        dot_name = f"{self.file.project.project_name}.dot"
        if dir is not None:
            dot_path = os.path.join(dir, dot_name)
        else:
            dot_path = os.path.join(self.dot_dir, dot_name)
        nx.nx_agraph.write_dot(self.pdg.g, dot_path)

    def write_code(self, dir: str | None = None):
        assert self.method_dir is not None
        file_name = f"{self.file.project.project_name}{self.file_suffix}"
        if dir is not None:
            code_path = os.path.join(dir, file_name)
        else:
            code_path = os.path.join(self.method_dir, file_name)
        with open(code_path, "w") as f:
            f.write(self.code)

    def code_by_lines_ppathf(self, remain_sliced_lines: set[int], *, placeholder: bool = False) -> tuple[str, dict[str, str]]:
        place_holder_map = {}
        if not placeholder:
            result = "\n".join([self.rel_lines[line] for line in sorted(remain_sliced_lines)])
            return result + "\n", place_holder_map
        else:
            code_with_placeholder = ""
            last_line = 0
            placeholder_counter = 0
            for line in sorted(remain_sliced_lines):
                if line - last_line > 1:
                    is_comment = True
                    for i in range(last_line + 1, line):
                        if self.rel_lines[i].strip() == "":
                            continue
                        if not self.rel_lines[i].strip().startswith("//"):
                            is_comment = False
                            break
                    if is_comment:
                        pass
                    elif line - last_line == 2 and (self.rel_lines[line - 1].strip() == "" or self.rel_lines[line - 1].strip().startswith("//")):
                        pass
                    else:
                        code_with_placeholder += f"/* Placeholder_{placeholder_counter} */\n"

                        if f"/* Placeholder_{placeholder_counter} */" not in place_holder_map:
                            place_holder_map[f"/* Placeholder_{placeholder_counter} */"] = ""
                            for i in range(last_line + 1, line):
                                place_holder_map[f"/* Placeholder_{placeholder_counter} */"] += self.rel_lines[i] + "\n"

                        placeholder_counter += 1
                code_with_placeholder += self.rel_lines[line] + "\n"
                last_line = line
            return code_with_placeholder, place_holder_map

    @staticmethod
    def backward_slice(criteria_lines: set[int], criteria_nodes: list[PDGNode], criteria_identifier: dict[int, set[str]], all_nodes: dict[int, list[PDGNode]], level: int) -> tuple[set[int], list[PDGNode]]:
        result_lines = criteria_lines.copy()
        result_nodes = criteria_nodes.copy()
        if level == 0:
            level = 1000

        # CFG 切片
        for slice_line in criteria_lines:
            for node in all_nodes[slice_line]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                for pred_node in node.pred_cfg_nodes:
                    if pred_node.line_number is None or int(pred_node.line_number) == sys.maxsize:
                        continue
                    result_lines.add(int(pred_node.line_number))
                    result_nodes.append(pred_node)

        # DDG 切片
        for sline in criteria_lines:
            for node in all_nodes[sline]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                visited = set()
                queue: deque[tuple[PDGNode, int]] = deque([(node, 0)])
                while queue:
                    node, depth = queue.popleft()
                    if node not in visited:
                        visited.add(node)
                        if node not in result_nodes:
                            result_nodes.append(node)
                        if node.line_number is not None:
                            result_lines.add(node.line_number)
                        if depth < level:
                            for pred_node, edge in node.pred_ddg:
                                if pred_node.line_number is None or int(pred_node.line_number) == sys.maxsize or node.line_number is None:
                                    continue
                                if pred_node.line_number > node.line_number:
                                    continue
                                if edge not in node.code:
                                    continue
                                if len(criteria_identifier) > 0:
                                    if node.line_number in criteria_identifier:
                                        if edge not in criteria_identifier[node.line_number]:
                                            continue
                                queue.append((pred_node, depth + 1))

        return result_lines, result_nodes

    @staticmethod
    def forward_slice(criteria_lines: set[int], criteria_nodes: list[PDGNode], criteria_identifier: dict[int, set[str]], all_nodes: dict[int, list[PDGNode]], level: int) -> tuple[set[int], list[PDGNode]]:
        result_lines = criteria_lines.copy()
        result_nodes = criteria_nodes.copy()
        if level == 0:
            level = 1000

        for slice_line in criteria_lines:
            for node in all_nodes[slice_line]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                if node.line_number is None:
                    continue
                for succ_node in node.succ_cfg_nodes:
                    if succ_node.line_number is None or int(succ_node.line_number) == sys.maxsize:
                        continue
                    if succ_node.line_number < node.line_number:
                        continue
                    result_lines.add(int(succ_node.line_number))
                    result_nodes.append(succ_node)

        for sline in criteria_lines:
            for node in all_nodes[sline]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                visited = set()
                queue: deque[tuple[PDGNode, int]] = deque([(node, 0)])
                while queue:
                    node, depth = queue.popleft()
                    if node not in visited:
                        visited.add(node)
                        if node not in result_nodes:
                            result_nodes.append(node)
                        if node.line_number is not None:
                            result_lines.add(node.line_number)
                        if depth < level:
                            for succ_node, edge in node.succ_ddg:
                                if edge not in node.code:
                                    continue
                                if succ_node.line_number is None or int(succ_node.line_number) == sys.maxsize or node.line_number is None:
                                    continue
                                if succ_node.line_number < node.line_number:
                                    continue
                                if node.line_number in criteria_identifier:
                                    if edge not in criteria_identifier[node.line_number]:
                                        continue
                                queue.append((succ_node, depth + 1))

        return result_lines, result_nodes

    def slice(self, criteria_lines: set[int], criteria_identifier: dict[int, set[str]], backward_slice_level: int = 4, forward_slice_level: int = 4, is_rel: bool = False):
        assert self.pdg is not None
        if is_rel:
            criteria_lines = set([line + self.start_line - 1 for line in criteria_lines])

        all_lines = set(self.lines.keys())
        all_nodes: dict[int, list[PDGNode]] = {
            line: self.pdg.get_nodes_by_line_number(line) for line in all_lines
        }
        criteria_nodes: list[PDGNode] = []
        for line in criteria_lines:
            for node in self.pdg.get_nodes_by_line_number(line):
                node.is_patch_node = True
                node.add_attr("color", "red")
                criteria_nodes.append(node)

        slice_result_lines = set(criteria_lines)
        slice_result_lines |= self.header_lines
        slice_result_lines.add(self.end_line)

        # PDG 切片
        result_lines, backward_nodes = self.backward_slice(
            criteria_lines, criteria_nodes, criteria_identifier, all_nodes, backward_slice_level)
        slice_result_lines.update(result_lines)
        result_lines, forward_nodes = self.forward_slice(
            criteria_lines, criteria_nodes, criteria_identifier, all_nodes, forward_slice_level)
        slice_result_lines.update(result_lines)
        slice_nodes = criteria_nodes + backward_nodes + forward_nodes
        slice_result_rel_lines = set(
            [line - self.start_line + 1 for line in slice_result_lines if line >= self.start_line])

        if self.length < 10:
            slice_result_rel_lines = self.rel_line_set
            slice_result_lines = set([line + self.start_line - 1 for line in slice_result_rel_lines])
            sliced_code = self.code_by_lines(slice_result_rel_lines)
            return slice_result_lines, slice_result_rel_lines, slice_nodes, self.code

        ast = ASTParser(self.code, self.language)
        if self.language == Language.C:
            body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
            if body_node is None:
                return
            slice_result_rel_lines = self.ast_add(ast, body_node, slice_result_rel_lines)
            slice_result_rel_lines = self.ast_trim(ast, body_node, slice_result_rel_lines)

        if self.language == Language.JAVA:
            body_node = ast.query_oneshot("(method_declaration body: (block)@body)")
            if body_node is None:
                return
            slice_result_rel_lines = self.ast_dive_java(body_node, slice_result_rel_lines)
            slice_result_lines = set([line + self.start_line - 1 for line in slice_result_rel_lines])
        elif self.language == Language.C:
            body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
            if body_node is None:
                return
            slice_result_rel_lines = self.ast_dive_c(body_node, slice_result_rel_lines)
            slice_result_lines = set([line + self.start_line - 1 for line in slice_result_rel_lines])
        sliced_code = self.code_by_lines(slice_result_rel_lines)
        return slice_result_lines, slice_result_rel_lines, slice_nodes, sliced_code

    def slice_by_diff_lines(self, backward_slice_level: int = 4, forward_slice_level: int = 4, need_criteria_identifier: bool = False, write_dot: bool = False):
        criteria_identifier = self.diff_identifiers if need_criteria_identifier else {}
        slice_results = self.slice(self.diff_lines, criteria_identifier,
                                   backward_slice_level, forward_slice_level, is_rel=False)
        if write_dot and slice_results is not None:
            assert self.pdg is not None and self.method_dir is not None
            slice_nodes = slice_results[2]
            g = nx.subgraph(self.pdg.g, [node.node_id for node in slice_nodes])
            os.makedirs(self.method_dir, exist_ok=True)
            role = self.file.project.project_name
            nx.nx_agraph.write_dot(g, os.path.join(
                self.dot_dir, f"{role}#{backward_slice_level}#{forward_slice_level}.dot"))
        return slice_results

    @staticmethod
    def ast_dive_java(root: Node, slice_lines: set[int]) -> set[int]:
        def is_in_node(line: int, node: Node) -> bool:
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            return node_start_line <= line <= node_end_line
        for node in root.named_children:
            tmp_lines = set()
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            for sline in slice_lines:
                if is_in_node(sline, node):
                    tmp_lines.add(sline)
            if len(tmp_lines) == 0:
                continue
            if node.type == "expression_statement":
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
            elif node.type == "if_statement":
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                slice_lines.update([node_start_line])
                slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                consequence_node = node.child_by_field_name("consequence")
                if consequence_node is None:
                    continue
                slice_lines.update([consequence_node.start_point[0] + 1, consequence_node.end_point[0] + 1])
                Method.ast_dive_java(consequence_node, slice_lines)

                alternative_node = node.child_by_field_name("alternative")
                if alternative_node is None:
                    continue
                next_alternative_node = alternative_node.child_by_field_name("alternative")
                if next_alternative_node is None:
                    slice_lines.update([alternative_node.start_point[0] + 1], [alternative_node.end_point[0] + 1])
                else:
                    slice_lines.update([alternative_node.start_point[0] + 1])
                Method.ast_dive_java(alternative_node, slice_lines)
            elif node.type == "try_statement":
                slice_lines.update([node_start_line, node_end_line])
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                Method.ast_dive_java(body_node, slice_lines)

                catch_node = ASTParser.children_by_type_name(node, "catch_clause")
                for node in catch_node:
                    slice_lines.update([node.start_point[0] + 1, node.end_point[0] + 1])
                    body_node = node.child_by_field_name("body")
                    if body_node is None:
                        continue
                    Method.ast_dive_java(body_node, slice_lines)

                finally_node = ASTParser.child_by_type_name(node, "finally_clause")
                if finally_node is None:
                    continue
                slice_lines.update([finally_node.start_point[0] + 1, finally_node.end_point[0] + 1])
                Method.ast_dive_java(finally_node, slice_lines)
            elif node.type == "for_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                init_node = node.child_by_field_name("init")
                if init_node is None:
                    continue
                if init_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([init_node.start_point[0] + 1, init_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                if condition_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                update_node = node.child_by_field_name("update")
                if update_node is None:
                    continue
                if update_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([update_node.start_point[0] + 1, update_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                Method.ast_dive_java(body_node, slice_lines)
            elif node.type == "block":
                slice_lines.update([node_start_line, node_end_line])
                Method.ast_dive_java(node, slice_lines)
            else:
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
        return slice_lines

    def ast_dive_c(self, root: Node, slice_lines: set[int]) -> set[int]:
        def is_in_node(line: int, node: Node) -> bool:
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            return node_start_line <= line <= node_end_line
        for node in root.named_children:
            tmp_lines = set()
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            for sline in slice_lines:
                if is_in_node(sline, node):
                    tmp_lines.add(sline)
            if len(tmp_lines) == 0:
                continue
            if node.type == "expression_statement":
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
            elif node.type == "if_statement":
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                slice_lines.update([node_start_line])
                slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                consequence_node = node.child_by_field_name("consequence")
                if consequence_node is None:
                    continue
                slice_lines.update([consequence_node.start_point[0] + 1, consequence_node.end_point[0] + 1])
                self.ast_dive_c(consequence_node, slice_lines)

                alternative_node = node.child_by_field_name("alternative")
                if alternative_node is None:
                    continue
                next_alternative_node = alternative_node.child_by_field_name("alternative")
                if next_alternative_node is None:
                    slice_lines.update([alternative_node.start_point[0] + 1], [alternative_node.end_point[0] + 1])
                else:
                    slice_lines.update([alternative_node.start_point[0] + 1])
                self.ast_dive_c(alternative_node, slice_lines)
            elif node.type == "for_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                slice_lines.update([node.start_point[0] + 1])
                slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                self.ast_dive_c(body_node, slice_lines)
            elif node.type == "switch_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                self.ast_dive_c(body_node, slice_lines)
            elif node.type == "case_statement":
                slice_lines.add(node_start_line)
                self.ast_dive_c(node, slice_lines)
            elif node.type == "block" or node.type == "compound_statement":
                slice_lines.update([node_start_line, node_end_line])
                self.ast_dive_c(node, slice_lines)
            else:
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
        return slice_lines

    def ast_trim(self, ast_parser: ASTParser, root: Node, slice_lines: set[int]) -> set[int]:
        if_statement_nodes = ast_parser.query_from_node(root, "(if_statement !alternative)@if")
        if_statement_nodes = [node[0] for node in if_statement_nodes if node[0].type == "if_statement"]
        for if_node in if_statement_nodes:
            if if_node.parent is not None and if_node.parent.type == "else_clause":
                continue
            condition_node = if_node.child_by_field_name("condition")
            consequence_node = if_node.child_by_field_name("consequence")
            if condition_node is None or consequence_node is None:
                continue
            if_node_lines = set(range(if_node.start_point[0] + 1, if_node.end_point[0] + 2))
            condition_lines = set(range(condition_node.start_point[0] + 1, condition_node.end_point[0] + 2))
            consequence_lines = set(range(consequence_node.start_point[0] + 1, consequence_node.end_point[0] + 1))
            assert consequence_node.text is not None
            if consequence_node.text.decode().startswith("{\n"):
                consequence_lines -= {consequence_node.start_point[0] + 1}
            if len(consequence_lines.intersection(slice_lines)) == 0:
                slice_lines -= if_node_lines
        return slice_lines

    def ast_add(self, ast_parser: ASTParser, root: Node, slice_lines: set[int]) -> set[int]:
        query = '''
        (if_statement
        consequence: (compound_statement
            [(goto_statement)
            (return_statement)
            (break_statement)]@jump
        )
        )@if
        '''
        results = ast_parser.query_from_node(root, query)
        if_node = [node[0] for node in results if node[1] == "if"]
        jump_node = [node[0] for node in results if node[1] == "jump"]
        for if_node, jump_node in zip(if_node, jump_node):
            if_node_lines = set(range(if_node.start_point[0] + 1, if_node.end_point[0] + 2))
            jump_node_lines = set(range(jump_node.start_point[0] + 1, jump_node.end_point[0] + 2))
            if len(if_node_lines.intersection(slice_lines)) != 0:
                slice_lines |= jump_node_lines

        query = """
        (case_statement
            (compound_statement
                [(break_statement)
                (goto_statement)
                (return_statement)]@jump
            )
        )@case
        (case_statement
            [(break_statement)
            (goto_statement)
            (return_statement)]@jump
        )@case
        """
        results = ast_parser.query_from_node(root, query)
        case_nodes = [node[0] for node in results if node[1] == "case"]
        jump_nodes = [node[0] for node in results if node[1] == "jump"]
        for case_node, jump_node in itertools.product(case_nodes, jump_nodes):
            if jump_node.parent is None:
                continue
            if jump_node.parent.parent is None:
                continue
            if jump_node.parent.id != case_node.id and jump_node.parent.parent.id != case_node.id:
                continue
            case_node_lines = set(range(case_node.start_point[0] + 1, case_node.end_point[0] + 2))
            break_node_lines = set(range(jump_node.start_point[0] + 1, jump_node.end_point[0] + 2))
            if len(case_node_lines.intersection(slice_lines)) != 0:
                slice_lines |= break_node_lines

        goto_query = """
        (goto_statement
        (statement_identifier)@label
        )
        """
        results = ast_parser.query_from_node(root, goto_query)
        for result in results:
            identifier_node = result[0]
            identifier_node_line = identifier_node.start_point[0] + 1
            if identifier_node_line not in slice_lines:
                continue
            assert identifier_node.text is not None
            identifier = identifier_node.text.decode()
            lable_query = f"""
            (labeled_statement
                label: (statement_identifier)@label
                (#eq? @label "{identifier}")
            )
            """
            result_node = ast_parser.query_oneshot(lable_query)
            if result_node is not None:
                slice_lines.add(result_node.start_point[0] + 1)

        return slice_lines

    @cached_property
    def line_number_pdg_map(self):
        assert self.file.project.joern is not None
        pdg_dir = os.path.join(self.file.project.joern.path, "pdg")
        dot_names = os.listdir(pdg_dir)
        for dot in dot_names:
            dot_path = os.path.join(pdg_dir, dot)
            try:
                pdg = joern.PDG(pdg_path=dot_path)
            except Exception as e:
                continue
            if pdg.name is None or pdg.line_number is None or pdg.filename is None:
                continue
            if pdg.line_number == self.start_line and pdg.filename == self.file.path:
                method_nodes = []
                line_map_method_nodes = pdg.line_map_method_nodes_id
                for line in line_map_method_nodes.keys():
                    method_nodes.extend(line_map_method_nodes[line])
                return [method_nodes, line_map_method_nodes]
        return []

    @property
    def caller(self):
        callers = []
        assert self.file.project.joern is not None
        cpg: nx.MultiDiGraph = self.file.project.joern.cpg.g
        if self.line_number_pdg_map == []:
            return []
        method_ids = self.line_number_pdg_map[0]
        line_map_method_nodes = self.line_number_pdg_map[1]
        for u, v, d in cpg.edges(data=True):
            if d['label'] == "CALL" and v in method_ids:
                line_number = cpg.nodes[u]['LINE_NUMBER']
                callers.append(line_number + "__split__" + u)

        return callers

    @property
    def callee(self):
        callees = []
        assert self.file.project.joern is not None
        cpg: nx.MultiDiGraph = self.file.project.joern.cpg.g
        method_ids = self.line_number_pdg_map[0]
        line_map_method_nodes = self.line_number_pdg_map[1]
        callees_define_signatures = {}
        for u, v, d in cpg.edges(data=True):
            if d['label'] == "CALL" and u in method_ids and 'LINE_NUMBER' in cpg.nodes[v].keys():
                line_number = next((key for key, value in line_map_method_nodes.items() if u in value), None)
                if line_number is None:
                    continue
                callees.append(line_number + "__split__" + v)
                callees_define_signatures[cpg.nodes[v]['NAME']] = ""

        print(callees)
        print(callees_define_signatures)

        for node in cpg.nodes:
            if cpg.nodes[node]['label'] != "METHOD":
                continue
            if cpg.nodes[node]['NAME'] in callees_define_signatures:
                method = self.file.project.get_method(
                    f"{cpg.nodes[node]['FILENAME'].split('/')[-1]}#{cpg.nodes[node]['NAME']}")
                if method is None:
                    print(f"NOT FOUND{cpg.nodes[node]['FILENAME'].split('/')[-1]}#{cpg.nodes[node]['NAME']}")
                    continue

                assert method is not None
                method_param_size = len(method.parameters)
                callees_define_signatures[cpg.nodes[node]['NAME']] = method_param_size

        return callees_define_signatures
