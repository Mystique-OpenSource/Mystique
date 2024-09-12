from __future__ import annotations

import ast
import copy
import logging
import os
import subprocess
import sys
from functools import cached_property

import networkx as nx

from ast_parser import TS_C_METHOD, ASTParser
from common import Language


def set_joern_env(joern_path: str):
    os.environ["PATH"] = joern_path + os.pathsep + os.environ["PATH"]
    assert subprocess.run(['which', 'joern'], stdout=subprocess.PIPE).stdout.decode(
    ).strip() == joern_path + "/joern"
    os.environ['JOERN_HOME'] = joern_path


def export(code_path: str, output_path: str, language: Language, overwrite: bool = False):
    pdg_dir = os.path.join(output_path, 'pdg')
    cfg_dir = os.path.join(output_path, 'cfg')
    cpg_dir = os.path.join(output_path, 'cpg')
    cpg_bin = os.path.join(output_path, 'cpg.bin')
    if os.path.exists(pdg_dir) and os.path.exists(cfg_dir) and os.path.exists(cpg_dir) and not overwrite:
        return
    else:
        if os.path.exists(pdg_dir):
            subprocess.run(['rm', '-rf', pdg_dir])
        if os.path.exists(cpg_dir):
            subprocess.run(['rm', '-rf', cfg_dir])
        if os.path.exists(cpg_bin):
            subprocess.run(['rm', '-rf', cpg_bin])
        if os.path.exists(cpg_dir):
            subprocess.run(['rm', '-rf', cpg_dir])

    error_code_cache = None
    error_file_path = None
    if language == Language.C:
        code_file_n = 0
        file_path = None
        for root, dirs, files in os.walk(code_path):
            for file in files:
                if file.endswith(".c") or file.endswith(".h"):
                    code_file_n += 1
                    file_path = os.path.join(root, file)
        if code_file_n == 1:
            assert file_path is not None
            with open(file_path, 'r+') as f:
                code = f.read()
                line_number = len(code.strip().split("\n"))
                code_ast = ASTParser(code, language)
                function_node = code_ast.query_oneshot(TS_C_METHOD)
                if function_node is not None:
                    function_len = function_node.end_point[0] - function_node.start_point[0] + 1
                    if function_len == line_number:
                        error_nodes = code_ast.get_error_nodes()
                        for node in error_nodes:
                            if node.start_point[0] != 0 and node.end_point[0] != 0:
                                continue
                            if len(node.named_children) != 1:
                                continue
                            identifier_node = node.named_children[0]
                            if identifier_node.type != "identifier":
                                continue
                            assert identifier_node.text is not None
                            identifier = identifier_node.text.decode()
                            error_file_path = file_path
                            error_code_cache = code
                            code = code.replace(identifier, "", 1)
                            f.seek(0)
                            f.write(code)
                            f.truncate()
                        call_node = code_ast.query_oneshot("(function_declarator(call_expression)@call)")
                        if call_node is not None:
                            assert call_node.text is not None
                            call = call_node.text.decode()
                            error_file_path = file_path
                            error_code_cache = code
                            code = code.replace(call, "", 1)
                            f.seek(0)
                            f.write(code)
                            f.truncate()

    if language == Language.CPP:
        lang = Language.C.value
    else:
        lang = language.value
    subprocess.run(['joern-parse', '--language', lang, os.path.abspath(code_path)],
                   cwd=output_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['joern-export', '--repr', 'cfg', '--out', os.path.abspath(cfg_dir)],
                   cwd=output_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['joern-export', '--repr', 'pdg', '--out', os.path.abspath(pdg_dir)],
                   cwd=output_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['joern-export', '--repr', 'all', '--out', os.path.abspath(cpg_dir)],
                   cwd=output_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if error_code_cache is not None and error_file_path is not None:
        with open(error_file_path, "w") as f:
            f.write(error_code_cache)


def joern_script_run(cpgFile: str, script_path: str, output_path: str):
    subprocess.run(['joern', '--script', script_path,
                    '--param', f"cpgFile={cpgFile}",
                    "--param", f"outFile={output_path}"],
                   cwd=os.path.dirname(cpgFile))


def preprocess(pdg_dir: str, cfg_dir: str, cpg_dir: str, need_cdg: bool):
    cpg = nx.nx_agraph.read_dot(os.path.join(cpg_dir, 'export.dot'))
    for pdg_file in os.listdir(pdg_dir):
        file_id = pdg_file.split('-')[0]
        try:
            pdg: nx.MultiDiGraph = nx.nx_agraph.read_dot(os.path.join(pdg_dir, pdg_file))
            cfg: nx.MultiDiGraph = nx.nx_agraph.read_dot(os.path.join(cfg_dir, f'{file_id}-cfg.dot'))
        except Exception as e:
            logging.error(f"Error in reading {pdg_file} or {file_id}-cfg.dot")
            os.remove(os.path.join(pdg_dir, pdg_file))
            os.remove(os.path.join(cfg_dir, f'{file_id}-cfg.dot'))
            continue

        ddg_null_edges = []
        for u, v, k, d in pdg.edges(data=True, keys=True):
            if need_cdg:
                null_edges_label = ['DDG: ', 'DDG: this']
            else:
                null_edges_label = ['DDG: ', 'CDG: ', 'DDG: this']
            if d['label'] in null_edges_label:
                ddg_null_edges.append((u, v, k, d))
        pdg.remove_edges_from(ddg_null_edges)

        pdg: nx.MultiDiGraph = nx.compose(pdg, cfg)
        for u, v, k, d in pdg.edges(data=True, keys=True):
            if 'label' not in d:
                pdg.edges[u, v, k]['label'] = 'CFG'

        method_node = None
        param_nodes = []
        for node in pdg.nodes:
            for key, value in cpg.nodes[node].items():
                pdg.nodes[node][key] = value
            pdg.nodes[node]['NODE_TYPE'] = pdg.nodes[node]['label']
            node_type = pdg.nodes[node]['NODE_TYPE']
            if node_type == 'METHOD':
                method_node = node
            if node_type == 'METHOD_PARAMETER_IN':
                param_nodes.append(node)
            if 'CODE' not in pdg.nodes[node]:
                pdg.nodes[node]['CODE'] = ''
            node_code = pdg.nodes[node]['CODE'].replace("\n", "\\n").replace(
                '"', r'__quote__').replace("\\", r'__Backslash__')
            pdg.nodes[node]['CODE'] = pdg.nodes[node]['CODE'].replace(
                "\n", "\\n").replace('"', r'__quote__').replace("\\", r'__Backslash__')
            node_line = pdg.nodes[node]['LINE_NUMBER'] if 'LINE_NUMBER' in pdg.nodes[node] else 0
            node_column = pdg.nodes[node]['COLUMN_NUMBER'] if 'COLUMN_NUMBER' in pdg.nodes[node] else 0
            pdg.nodes[node]['label'] = f"[{node}][{node_line}:{node_column}][{node_type}]: {node_code}"
            if pdg.nodes[node]['NODE_TYPE'] == 'METHOD_RETURN':
                pdg.remove_edges_from(list(pdg.in_edges(node)))
        for param_node in param_nodes:
            pdg.add_edge(method_node, param_node, label='DDG')

        nx.nx_agraph.write_dot(pdg, os.path.join(pdg_dir, pdg_file))


def merge(output_path: str, pdg_dir: str, code_dir: str, overwrite: bool = False):
    pdg_old_merge_dir = os.path.join(output_path, 'pdg_old_merge')
    if overwrite or not os.path.exists(pdg_old_merge_dir):
        if os.path.exists(pdg_old_merge_dir):
            subprocess.run(['rm', '-rf', pdg_old_merge_dir])
        subprocess.run(['cp', '-r', pdg_dir, pdg_old_merge_dir])
        for pdg_file in os.listdir(pdg_dir):
            try:
                pdg: nx.MultiDiGraph = nx.nx_agraph.read_dot(os.path.join(pdg_dir, pdg_file))
            except Exception as e:
                logging.error(f"Error in reading {pdg_file}")
                os.remove(os.path.join(pdg_dir, pdg_file))
                continue

            node_line_map = {}
            file_name = ""
            already_merged = False
            for node in pdg.nodes:
                if "INCLUDE_ID" in pdg.nodes[node].keys():
                    already_merged = True
                if 'CODE' not in pdg.nodes[node]:
                    pdg.nodes[node]['CODE'] = ''
                node_line = pdg.nodes[node]['LINE_NUMBER'] if 'LINE_NUMBER' in pdg.nodes[node] else 0
                if "FILENAME" in pdg.nodes[node].keys():
                    file_name = pdg.nodes[node]["FILENAME"]
                node_type = pdg.nodes[node]['NODE_TYPE']
                if node_type == 'METHOD':
                    continue
                try:
                    node_line_map[node_line].append(node)
                except:
                    node_line_map[node_line] = [node]
            if file_name == "":
                continue
            if already_merged:
                continue
            if not os.path.exists(os.path.join(code_dir, file_name)):
                continue

            fp = open(os.path.join(code_dir, file_name))
            full_code = fp.readlines()
            fp.close()
            for line in node_line_map:
                max_col = 0
                min_col = sys.maxsize
                new_node = pdg.nodes[node_line_map[line][0]].copy()
                code = full_code[int(line) - 1].strip().replace(r'"', r'__quote__').replace("\\", r'__Backslash__')
                new_node['label'] = f"[{node_line_map[line][0]}][{line}]:{code}"
                raw_code = pdg.nodes[node_line_map[line][0]]['CODE']
                new_node['CODE'] = full_code[int(line) - 1].strip().replace(r'"',
                                                                            r'__quote__').replace("\\", r'__Backslash__')
                new_node['INCLUDE_ID'] = {str(line): node_line_map[line]}
                for node in node_line_map[line]:
                    if node == node_line_map[line][0]:
                        code = raw_code
                    else:
                        code = pdg.nodes[node]['CODE']
                    for key, value in pdg.nodes[node].items():
                        if key in ["label", "LINE_NUMBER", "CODE", "FILENAME", "FULL_NAME", "LINE_NUMBER_END", ]:
                            continue
                        if key == "COLUMN_NUMBER":
                            min_col = min(min_col, int(value))
                            continue
                        if key == "COLUMN_NUMBER_END":
                            max_col = max(max_col, int(value))
                            continue
                        try:
                            new_node[key].append(value)
                        except:
                            new_node[key] = [value]
                new_node['COLUMN_NUMBER'] = min_col
                new_node['COLUMN_NUMBER_END'] = max_col
                for key, value in new_node.items():
                    pdg.nodes[node_line_map[line][0]][key] = value
                for i, node in enumerate(node_line_map[line]):
                    if i == 0:
                        continue
                    in_edges = copy.deepcopy(pdg.in_edges(node, data=True, keys=True))
                    out_edges = copy.deepcopy(pdg.out_edges(node, data=True, keys=True))
                    for u, v, k, d in in_edges:
                        if u == node_line_map[line][0]:
                            continue
                        pdg.add_edge(u, node_line_map[line][0], label=d['label'])
                    for u, v, k, d in out_edges:
                        if v == node_line_map[line][0]:
                            continue
                        pdg.add_edge(node_line_map[line][0], v, label=d['label'])
                    pdg.remove_edges_from(list(in_edges))
                    pdg.remove_node(node)

            edges = set()
            raw_edges = copy.deepcopy(pdg.edges(data=True, keys=True))
            for u, v, k, d in raw_edges:
                if f"{u}__split__{v}__split__{d['label']}" in edges:
                    pdg.remove_edge(u, v, k)
                else:
                    edges.add(f"{u}__split__{v}__split__{d['label']}")
            nx.nx_agraph.write_dot(pdg, os.path.join(pdg_dir, pdg_file))


def add_cfg_lines(output_path: str, pdg_dir: str, code_dir: str, cpg_dir: str, overwrite: bool = False):
    pdg_old_add_var_def_dir = os.path.join(output_path, 'pdg_old_def')
    if overwrite or not os.path.exists(pdg_old_add_var_def_dir):
        if os.path.exists(pdg_old_add_var_def_dir):
            subprocess.run(['rm', '-rf', pdg_old_add_var_def_dir])
        subprocess.run(['cp', '-r', pdg_dir, pdg_old_add_var_def_dir])

        cpg = nx.nx_agraph.read_dot(os.path.join(cpg_dir, 'export.dot'))
        ids = set()
        for node in cpg.nodes:
            ids.add(int(node))
        max_id = max(ids) + 1
        for pdg_file in os.listdir(pdg_dir):
            try:
                pdg: nx.MultiDiGraph = nx.nx_agraph.read_dot(os.path.join(pdg_dir, pdg_file))
            except Exception as e:
                logging.error(f"Error in reading {pdg_file}")
                os.remove(os.path.join(pdg_dir, pdg_file))
                continue
            file_name = ""
            method_node = None
            lines = set()
            line_node_map = {}
            for node in pdg.nodes:
                node_line = pdg.nodes[node]['LINE_NUMBER'] if 'LINE_NUMBER' in pdg.nodes[node] else 0
                line_node_map[int(node_line)] = node
                lines.add(int(node_line))
                if "FILENAME" in pdg.nodes[node].keys():
                    file_name = pdg.nodes[node]["FILENAME"]
                if pdg.nodes[node]['NODE_TYPE'] == "METHOD":
                    method_node = node
                elif "LINE_NUMBER_END" in pdg.nodes[node].keys():
                    lines.add(i for i in range(int(pdg.nodes[node]["LINE_NUMBER"]), int(
                        pdg.nodes[node]["LINE_NUMBER_END"] + 1)))
            if method_node is None:
                continue
            if not os.path.exists(os.path.join(code_dir, file_name)):
                continue
            fp = open(os.path.join(code_dir, file_name))
            full_code = fp.readlines()
            fp.close()
            line = int(pdg.nodes[method_node]["LINE_NUMBER"]) if 'LINE_NUMBER' in pdg.nodes[method_node] else 0
            if "LINE_NUMBER_END" not in pdg.nodes[method_node].keys():
                continue
            while line < int(pdg.nodes[method_node]["LINE_NUMBER_END"]):
                if line in lines:
                    line += 1
                    continue
                if full_code[line - 1].replace(" ", "").replace("{", "").replace("}", "").replace("\t", "").replace("\n", "").replace("(", "").replace(")", "") == "":
                    line += 1
                    continue
                code = full_code[int(line) - 1].strip().replace(r'"', r'__quote__').replace("\\", r'__Backslash__')
                new_node_attr = {"CODE": full_code[int(line) - 1].strip().replace(r'"', r'__quote__').replace("\\", r'__Backslash__'),
                                 "label": f"[{max_id}][{line}][variable_declaration]:{code}",
                                 "INCLUDE_ID": {f"{line}": f"[{max_id}]"},
                                 "LINE_NUMBER": line,
                                 "NODE_TYPE": ["variable_declaration"]}

                pdg.add_node(max_id, **new_node_attr)
                if line - 1 in line_node_map.keys():
                    pdg.add_edge(line_node_map[line - 1], max_id, label="CFG")
                if line + 1 in lines and line + 1 in line_node_map.keys():
                    pdg.add_edge(max_id, line_node_map[line + 1], label="CFG")
                line_node_map[line] = max_id
                max_id += 1
                line += 1
            nx.nx_agraph.write_dot(pdg, os.path.join(pdg_dir, pdg_file))


def export_with_preprocess(code_path: str, output_path: str, language: Language, need_cdg: bool = False, overwrite: bool = False):
    export(code_path=code_path, output_path=output_path, language=language, overwrite=overwrite)
    pdg_dir = os.path.join(output_path, 'pdg')
    cfg_dir = os.path.join(output_path, 'cfg')
    cpg_dir = os.path.join(output_path, 'cpg')
    pdg_old_dir = os.path.join(output_path, 'pdg-old')
    if overwrite or not os.path.exists(pdg_old_dir):
        if os.path.exists(pdg_old_dir):
            subprocess.run(['rm', '-rf', pdg_old_dir])
        subprocess.run(['cp', '-r', pdg_dir, pdg_old_dir])
        preprocess(pdg_dir, cfg_dir, cpg_dir, need_cdg)


def export_with_preprocess_and_merge(code_path: str, output_path: str, language: Language, need_cdg: bool = True, overwrite: bool = False):
    pdg_dir = os.path.join(output_path, 'pdg')
    cpg_dir = os.path.join(output_path, 'cpg')
    if not os.path.exists(os.path.join(cpg_dir, 'export.dot')):
        overwrite = True
    export_with_preprocess(code_path, output_path, language, need_cdg, overwrite)
    merge(output_path, pdg_dir, code_path, overwrite)
    add_cfg_lines(output_path, pdg_dir, code_path, cpg_dir, overwrite)


class CPGNode:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.attr = {}

    def __hash__(self):
        return hash(self.node_id)

    def __eq__(self, node: object):
        if not isinstance(node, CPGNode):
            return False
        if self.node_id == node.node_id:
            return True
        else:
            return False

    def get_value(self, key: str) -> str | None:
        if key in self.attr:
            return self.attr[key]
        else:
            return None

    def set_attr(self, key: str, value: str):
        self.attr[key] = value


class Edge:
    def __init__(self, edge_id: tuple[int, int]):
        self.edge_id = edge_id
        self.attr: list[tuple[int, int]] = []

    def set_attr(self, key, value):
        self.attr.append((key, value))


class CPG:
    def __init__(self, cpg_dir: str):
        self.cpg_dir = cpg_dir
        cpg_path = os.path.join(cpg_dir, 'export.dot')
        if not os.path.exists(cpg_path):
            raise FileNotFoundError(f"export.dot is not found in {cpg_path}")
        self.g: nx.MultiDiGraph = nx.nx_agraph.read_dot(cpg_path)

    def get_node(self, node_id: int) -> dict[str, str]:
        return self.g.nodes[node_id]

    def _init__(self, cpg_dir: str):
        self.cpg_dir = cpg_dir
        cpg_path = os.path.join(cpg_dir, 'export.dot')
        if not os.path.exists(cpg_path):
            raise FileNotFoundError(f"export.dot is not found in {cpg_path}")
        cpg_nx: nx.MultiDiGraph = nx.nx_agraph.read_dot(cpg_path)
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()
        for nx_node in cpg_nx.nodes():
            node_type = cpg_nx.nodes[nx_node]['label']
            node = self._parser_node(node_type, int(nx_node), cpg_nx.nodes[nx_node])
            self.g.add_node(int(nx_node), **node.to_dict())
        for u, v, data in cpg_nx.edges(data=True):
            src = int(u)
            dst = int(v)
            self.g.add_edge(src, dst, **data)
        for u, v, data in self.g.edges(data=True):
            print(u, v, data)


class PDGNode:
    def __init__(self, node_id: int, attr: dict[str, str], pdg: PDG):
        self.node_id: int = node_id
        self.attr: dict[str, str] = attr
        self.pdg: PDG = pdg
        self.is_patch_node = False

    def __hash__(self):
        return hash(self.node_id)

    def __eq__(self, node: object):
        if not isinstance(node, PDGNode):
            return False
        if self.node_id == node.node_id:
            return True
        else:
            return False

    @property
    def line_number(self) -> int | None:
        if 'LINE_NUMBER' not in self.attr:
            return None
        return int(self.attr['LINE_NUMBER'])

    @property
    def type(self) -> str:
        return self.attr['NODE_TYPE']

    @property
    def code(self) -> str:
        if 'CODE' not in self.attr:
            return ''
        return self.attr['CODE'].replace(r'__quote__', r'"').replace("__Backslash__", r'\\')

    @property
    def get_successors(self) -> list[PDGNode]:
        nodes = []
        for node in self.pdg.g.successors(self.node_id):
            nodes.append(PDGNode(node, self.pdg.g.nodes[node], self.pdg))
        return nodes

    @property
    def get_predecessors(self) -> list[PDGNode]:
        nodes = []
        for node in self.pdg.g.predecessors(self.node_id):
            nodes.append(PDGNode(node, self.pdg.g.nodes[node], self.pdg))
        return nodes

    def get_predecessors_by_label(self, label: str) -> list[tuple[PDGNode, str]]:
        nodes = []
        for node in self.pdg.g.predecessors(self.node_id):
            for _, edge in self.pdg.g[node][self.node_id].items():
                if edge['label'].startswith(label):
                    if "&gt;" in edge['label']:
                        edge['label'] = edge['label'].replace("&gt;", ">")
                    elif "&lt;" in edge['label']:
                        edge['label'] = edge['label'].replace("&lt;", "<")
                    nodes.append((PDGNode(node, self.pdg.g.nodes[node], self.pdg), edge['label']))
        return nodes

    def get_successors_by_label(self, label: str) -> list[tuple[PDGNode, str]]:
        nodes = []
        for node in self.pdg.g.successors(self.node_id):
            for _, edge in self.pdg.g[self.node_id][node].items():
                if edge['label'].startswith(label):
                    if "&gt;" in edge['label']:
                        edge['label'] = edge['label'].replace("&gt;", ">")
                    elif "&lt;" in edge['label']:
                        edge['label'] = edge['label'].replace("&lt;", "<")
                    nodes.append((PDGNode(node, self.pdg.g.nodes[node], self.pdg), edge['label']))
        return nodes

    @property
    def pred_dominance(self) -> PDGNode | None:
        assert self.line_number is not None
        pred = self.get_predecessors_by_label('CFG')
        nodes = [node for node, _ in pred]
        min_distance = sys.maxsize
        dominance = None
        for node in nodes:
            if node.line_number is None or node.line_number >= self.line_number:
                continue
            if self.line_number - node.line_number < min_distance:
                min_distance = self.line_number - node.line_number
                dominance = node
        if dominance is None:
            pred = self.get_predecessors_by_label('CDG')
            nodes = [node for node, _ in pred]
            min_distance = sys.maxsize
            dominance = None
            for node in nodes:
                if node.line_number is None or node.line_number >= self.line_number:
                    continue
                if self.line_number - node.line_number < min_distance:
                    min_distance = self.line_number - node.line_number
                    dominance = node
        return dominance

    @property
    def succ_dominance(self) -> PDGNode | None:
        assert self.line_number is not None
        succ = self.get_successors_by_label('CFG')
        nodes = [node for node, _ in succ]
        min_distance = sys.maxsize
        dominance = None
        for node in nodes:
            if node.line_number is None or node.line_number <= self.line_number:
                continue
            if node.line_number - self.line_number < min_distance:
                min_distance = node.line_number - self.line_number
                dominance = node

        if dominance is None:
            succ = self.get_successors_by_label('CDG')
            nodes = [node for node, _ in succ]
            min_distance = sys.maxsize
            dominance = None
            for node in nodes:
                if node.line_number is None or node.line_number <= self.line_number:
                    continue
                if node.line_number - self.line_number < min_distance:
                    min_distance = node.line_number - self.line_number
                    dominance = node
        return dominance

    @property
    def pred_cfg_nodes(self) -> list[PDGNode]:
        pred = self.get_predecessors_by_label('CFG')
        return [node for node, _ in pred]

    @property
    def succ_cfg_nodes(self) -> list[PDGNode]:
        succ = self.get_successors_by_label('CFG')
        return [node for node, _ in succ]

    @property
    def pred_ddg_nodes(self) -> list[PDGNode]:
        pred = self.get_predecessors_by_label('DDG')
        return [node for node, _ in pred]

    @property
    def pred_ddg(self) -> list[tuple[PDGNode, str]]:
        pred_ddg = self.get_predecessors_by_label('DDG')
        pred_ddg = [(node, e.replace('DDG: ', '')) for node, e in pred_ddg]
        return pred_ddg

    @property
    def succ_ddg(self) -> list[tuple[PDGNode, str]]:
        succ_ddg = self.get_successors_by_label('DDG')
        succ_ddg = [(node, e.replace('DDG: ', '')) for node, e in succ_ddg]
        return succ_ddg

    @property
    def succ_ddg_nodes(self) -> list[PDGNode]:
        succ = self.get_successors_by_label('DDG')
        return [node for node, _ in succ]

    def add_attr(self, key: str, value: str):
        self.attr[key] = value


class PDG:
    def __init__(self, pdg_path: str) -> None:
        self.pdg_path = pdg_path
        if not os.path.exists(self.pdg_path):
            raise FileNotFoundError(f"dot file is not found in {self.pdg_path}")

        self.g: nx.MultiDiGraph = nx.nx_agraph.read_dot(pdg_path)
        if self.method_node is None:
            raise ValueError("METHOD node is not found")

    @property
    def line_map_method_nodes(self):
        line_map_method_nodes = {self.method_node: [self.method_node]}
        for node in self.g.nodes():
            if "INCLUDE_ID" not in self.g.nodes[node].keys():
                continue
            else:
                line_map_method_nodes.update(ast.literal_eval(self.g.nodes[node]['INCLUDE_ID']))
        return line_map_method_nodes

    @property
    def line_map_method_nodes_id(self):
        return self.line_map_method_nodes

    @cached_property
    def method_node(self) -> PDGNode | None:
        for node in self.g.nodes():
            if self.g.nodes[node]['NODE_TYPE'] == 'METHOD':
                return node

    @property
    def filename(self) -> str | None:
        return self.g.nodes[self.method_node]["FILENAME"]

    @property
    def line_number(self) -> int | None:
        if "LINE_NUMBER" not in self.g.nodes[self.method_node]:
            return None
        return int(self.g.nodes[self.method_node]["LINE_NUMBER"])

    @property
    def name(self) -> str | None:
        try:
            name_attr = self.g.nodes[self.method_node]["NAME"]
        except KeyError:
            return None
        return name_attr

    def get_node(self, node_id) -> PDGNode:
        return PDGNode(node_id, self.g.nodes[node_id], self)

    def get_nodes_by_line_number(self, line_number: int) -> list[PDGNode]:
        nodes: list[PDGNode] = []
        for node, attr in self.g.nodes.items():
            if 'LINE_NUMBER' not in attr:
                continue
            if attr['LINE_NUMBER'] == str(line_number):
                pdg_node = PDGNode(node, attr, self)
                nodes.append(pdg_node)
        return nodes
