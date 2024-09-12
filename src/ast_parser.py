from typing import Generator

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

import common

TS_JAVA_PACKAGE = "(package_declaration (scoped_identifier) @package)(package_declaration (identifier) @package)"
TS_JAVA_IMPORT = "(import_declaration (scoped_identifier) @import)"
TS_JAVA_CLASS = "(class_declaration) @class"
TS_JAVA_FIELD = "(field_declaration) @field"
TS_C_INCLUDE = "(preproc_include (system_lib_string)@string_content)(preproc_include (string_literal)@string_content)"
TS_C_METHOD = "(function_definition)@method"
TS_COND_STAT = "(if_statement)@name (while_statement)@name (for_statement)@name"
TS_ASSIGN_STAT = "(assignment_expression)@name"
TS_JAVA_METHOD = "(method_declaration) @method (constructor_declaration) @method"
TS_METHODNAME = "(method_declaration 	(identifier)@id)(constructor_declaration 	(identifier)@id)"
TS_FPARAM = "(formal_parameters)@name"


class ASTParser:
    def __init__(self, code: str | bytes, language: common.Language | int):
        if language == common.Language.C:
            self.LANGUAGE = Language(tsc.language())
        elif language == common.Language.CPP:
            self.LANGUAGE = Language(tscpp.language())
        elif language == common.Language.JAVA:
            self.LANGUAGE = Language(tsjava.language())
        else:
            self.LANGUAGE = Language(tsc.language())
        self.parser = Parser(self.LANGUAGE)
        if isinstance(code, str):
            self.tree = self.parser.parse(bytes(code, "utf-8"))
        elif isinstance(code, bytes):
            self.tree = self.parser.parse(code)
        self.root = self.tree.root_node

    @staticmethod
    def children_by_type_name(node: Node, type: str) -> list[Node]:
        node_list = []
        for child in node.named_children:
            if child.type == type:
                node_list.append(child)
        return node_list

    @staticmethod
    def child_by_type_name(node: Node, type: str) -> Node | None:
        for child in node.named_children:
            if child.type == type:
                return child
        return None

    def traverse_tree(self) -> Generator[Node, None, None]:
        cursor = self.tree.walk()
        visited_children = False
        while True:
            if not visited_children:
                assert cursor.node is not None
                yield cursor.node
                if not cursor.goto_first_child():
                    visited_children = True
            elif cursor.goto_next_sibling():
                visited_children = False
            elif not cursor.goto_parent():
                break

    def query_oneshot(self, query_str: str) -> Node | None:
        query = self.LANGUAGE.query(query_str)
        captures = query.captures(self.root)
        result = None
        for capture in captures:
            result = capture[0]
            break
        return result

    def query(self, query_str: str):
        query = self.LANGUAGE.query(query_str)
        captures = query.captures(self.root)
        return captures

    def query_from_node(self, node: Node, query_str: str):
        query = self.LANGUAGE.query(query_str)
        captures = query.captures(node)
        return captures

    def get_error_nodes(self) -> list[Node]:
        query_str = """
        (ERROR)@error
        """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_identifier_node(self) -> list[Node]:
        query_str = """
        (identifier) @id
        """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_conditional_node(self) -> list[Node]:
        query_str = TS_COND_STAT
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_assign_node(self) -> list[Node]:
        query_str = """
        (assignment_expression)@name  ( declaration )@name
        """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_return_node(self) -> list[Node]:
        query_str = """
        (return_statement)@name
        """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_call_node(self) -> list[Node]:
        query_str = """
        (call_expression)@name
        """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res

    def get_all_includes(self) -> list[Node]:
        if self.LANGUAGE == Language(tscpp.language()) or self.LANGUAGE == Language(tsc.language()):
            query_str = """
            (preproc_include)@name
            """
        else:
            query_str = """
            ( import_declaration)@name
            """
        captures = self.query(query_str)
        res = []
        for capture in captures:
            res.append(capture[0])
        return res
