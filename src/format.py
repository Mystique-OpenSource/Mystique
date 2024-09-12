import re
import subprocess

import ast_parser
from ast_parser import ASTParser
from common import Language


def astyle(code: str) -> str:
    code = subprocess.run(['astyle', '--style=java', '--squeeze-ws', '--keep-one-line-statements',
                           '--max-code-length=200', '--delete-empty-lines'], input=code.encode(), stdout=subprocess.PIPE).stdout.decode().strip()
    return code


def remove_comments(string):
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def _replacer(match):
        if match.group(2) is not None:
            return ""
        else:
            return match.group(1)
    return regex.sub(_replacer, string)


def del_comment_java(file_contents):
    c_regex = re.compile(
        r'(?P<comment>//.*?$)|(?P<multilinecomment>/\*.*?\*/)|(?P<noncomment>\'(\\.|[^\\\'])*\'|"(\\.|[^\\"])*"|.[^/\'"]*)',
        re.DOTALL | re.MULTILINE,
    )
    file_contents = "".join(
        [
            c.group("noncomment")
            for c in c_regex.finditer(file_contents)
            if c.group("noncomment")
        ]
    )
    return file_contents


def get_comment(code):
    c_regex = re.compile(
        r'(?P<comment>//.*?$)|(?P<multilinecomment>/\*.*?\*/)|(?P<noncomment>\'(\\.|[^\\\'])*\'|"(\\.|[^\\"])*"|.[^/\'"]*)',
        re.DOTALL | re.MULTILINE,
    )
    comment = [
        c.group("comment")
        for c in c_regex.finditer(code)
        if c.group("comment")
    ]
    multilinecomment = [
        c.group("multilinecomment")
        for c in c_regex.finditer(code)
        if c.group("multilinecomment")
    ]
    all_comment = set()
    for comma in comment:
        all_comment.add(comma)
    for comma in multilinecomment:
        all_comment.add(comma)
    return all_comment


def remove_linebreaks(string):
    return re.sub(r"\n", "", string)


def remove_spaces(string):
    return re.sub(r"\s+", "", string)


def remove_empty_lines(string) -> str:
    return re.sub(r"^\s*$\n", "", string, flags=re.MULTILINE)


def remove_param_linebreaks(string) -> str:
    return re.sub(r",\s*", ", ", string)


def normalize(code: str, del_comments: bool = True) -> str:
    if del_comments:
        code = remove_comments(code)
    code = remove_linebreaks(code)
    code = remove_spaces(code)
    return code.strip()


def add_bracket_c(code: str, language: Language):
    code_bytes = code.encode()
    parser = ASTParser(code, language)
    nodes = parser.query(ast_parser.TS_COND_STAT)
    nodes = [node[0] for node in nodes]
    need_modified_bytes = []
    for node in nodes:
        consequence_node = node.child_by_field_name("consequence")
        if consequence_node is None:
            continue
        if consequence_node.type != "compound_statement":
            if (consequence_node.start_byte, consequence_node.end_byte) not in need_modified_bytes:
                need_modified_bytes.append((consequence_node.start_byte, consequence_node.end_byte))
        alternative_node = node.child_by_field_name("alternative")
        if alternative_node is None:
            continue
        alternative_node = alternative_node.named_child(0)
        if alternative_node is not None and alternative_node.type != "compound_statement" and alternative_node.type != "if_statement":
            if (alternative_node.start_byte, alternative_node.end_byte) not in need_modified_bytes:
                st = alternative_node.start_byte
                ed = alternative_node.end_byte
                need_modified_bytes.append((alternative_node.start_byte, alternative_node.end_byte))
    need_modified_bytes = sorted(need_modified_bytes)
    i = 0
    while i < len(need_modified_bytes):
        st, ed = need_modified_bytes[i]
        if ed - st <= 1:
            i += 1
            continue
        code_bytes = code_bytes[:st] + b"{\n" + code_bytes[st:ed + 1] + b"}\n" + code_bytes[ed + 1:]
        j = i + 1
        while j < len(need_modified_bytes):
            st_next, ed_next = need_modified_bytes[j]
            if st_next >= st and st_next <= ed:
                st_next += 2
            else:
                st_next += 4
            if ed_next >= st and ed_next <= ed:
                ed_next += 2
            else:
                ed_next += 4
            need_modified_bytes[j] = (st_next, ed_next)
            j += 1
        i += 1
    return code_bytes.decode()


def del_lineBreak_Java(code: str):
    comments = get_comment(code)
    comment_map = {}
    cnt = 0
    for comment in comments:
        repl = f"__COMMENT__{cnt};"
        code = code.replace(comment, repl)
        comment_map[repl] = comment
        cnt += 1
    lines = code.split("\n")
    i = 0
    while i < len(lines):
        if (
            lines[i].strip() == ""
            or lines[i].strip().startswith("@")
        ):
            i += 1
        else:
            temp = i
            while (
                i < len(lines)
                and not lines[i].strip().endswith(";")
                and not lines[i].strip().endswith("{")
                and not lines[i].strip().endswith(")")
                and not lines[i].strip().endswith("}")
                and not lines[i].strip().endswith(":")
                and not lines[i].strip().startswith("@")
            ):
                i += 1
            while i < len(lines) - 1 and (lines[i + 1].strip().startswith("?") or lines[i + 1].strip().startswith("||") or lines[i + 1].strip().startswith("&&") or lines[i + 1].strip().startswith(".")):
                i += 1
            if i < len(lines) and lines[i].strip().startswith("@"):
                i -= 1
            if temp != i:
                lines[temp] = lines[temp]
            for j in range(temp + 1, i + 1):
                if j == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[j].strip()
                lines[j] = ""
            if temp == i:
                i += 1
    code = "\n".join(lines)
    for repl in comment_map.keys():
        code = code.replace(repl, comment_map[repl])
    return code


def del_lineBreak_C(code):
    comments = get_comment(code)
    comment_map = {}
    cnt = 0
    for comment in comments:
        repl = f"__COMMENT__{cnt};"
        code = code.replace(comment, repl)
        comment_map[repl] = comment
        cnt += 1
    lines = code.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].endswith("\\"):
            temp = i
            while lines[i].endswith("\\"):
                i += 1
            lines[temp] = lines[temp][:-2]
            for k in range(temp + 1, i + 1):
                if k == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[k][:-2].strip()
                lines[k] = "\n"
        else:
            i += 1
    i = 0
    while i < len(lines):
        if (
            lines[i].strip() == ""
            or lines[i].strip().startswith("#")
        ):
            i += 1
        else:
            temp = i
            while (
                i < len(lines)
                and not lines[i].strip().endswith(";")
                and not lines[i].strip().endswith("{")
                and not lines[i].strip().endswith(")")
                and not lines[i].strip().endswith("}")
                and not lines[i].strip().endswith(":")
                and not lines[i].strip().startswith("#")
            ):
                i += 1
            while i < len(lines) - 1 and (lines[i + 1].strip().startswith("?") or lines[i + 1].strip().startswith("||") or lines[i + 1].strip().startswith("&&")):
                i += 1
            if i < len(lines) and lines[i].strip().startswith("#"):
                i -= 1
            if temp != i:
                lines[temp] = lines[temp]
            for j in range(temp + 1, i + 1):
                if j == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[j].strip()
                lines[j] = ""
            if temp == i:
                i += 1
    code = "\n".join(lines)
    for repl in comment_map.keys():
        code = code.replace(repl, comment_map[repl])
    return code


def del_macros(code):
    lines = code.split("\n")
    removed_macros = {"R_API", "INLINE", "TRIO_PRIVATE_STRING", "GF_EXPORT", "LOCAL", "IN", "OUT", "_U_", "EFIAPI",
                      "UNUSED_PARAM", "__declspec(dllexport) mrb_value", "extern \"C\"", "__rte_always_inline", "__init", "__user", "UNUSED"}
    i = 0
    while i < len(lines):
        if lines[i].endswith("\\"):
            temp = i
            while lines[i].endswith("\\"):
                i += 1
            lines[temp] = lines[temp][:-1]
            for k in range(temp + 1, i + 1):
                if k == len(lines):
                    break
                lines[temp] += " "
                if k != i:
                    lines[temp] += lines[k][:-1].strip()
                else:
                    lines[temp] += lines[k].strip()
                lines[k] = "\n"
        else:
            i += 1

    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("#") and not lines[i].strip().startswith("#include"):
            lines[i] = ""
        for rmv_macro in removed_macros:
            lines[i] = lines[i].replace(rmv_macro, "")
        lines[i] = lines[i].replace("METHODDEF(void)", "void").replace("METHODDEF(JDIMENSION)", "int")
        i += 1
    return "\n".join(lines)


def format_and_del_comment_c_cpp(code: str):
    code = astyle(code)
    code = remove_comments(code)
    code = del_macros(code)
    code = del_lineBreak_C(code)
    code = add_bracket_c(code, Language.C)
    code = remove_empty_lines(code)
    code = astyle(code)
    return code


def format_and_del_comment_java(code: str):
    code = remove_comments(code)
    code = del_lineBreak_Java(code)
    code = remove_empty_lines(code)
    return code


def format(code: str, language: Language, del_comment: bool, del_linebreak: bool, add_bracket: bool = True) -> str:
    code = astyle(code)
    if del_comment:
        code = del_comment_java(code)
    if del_linebreak:
        if language == Language.JAVA:
            code = del_lineBreak_Java(code)
        elif language == Language.C:
            code = del_lineBreak_C(code)
    if add_bracket:
        if language == Language.C:
            code = add_bracket_c(code, language)
    code = remove_empty_lines(code)
    code = astyle(code)
    return code


def format_file(file_path: str, language: Language, del_linebreak: bool) -> str:
    with open(file_path, 'r') as file:
        code = file.read()
    code = format(code, language, del_linebreak=del_linebreak, del_comment=True)
    return code
