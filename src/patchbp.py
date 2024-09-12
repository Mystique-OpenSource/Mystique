import difflib
import hashlib
import json
import logging
import os
import time

import cpu_heater

import config
import difftools
import format
import hunkmap
import llm
import log
import utils
from ast_parser import ASTParser
from codefile import CodeFile, create_code_tree
from common import ErrorCode, Language
from project import Method, Project


def sematic_enhance_patch(rel_pre_lines: set[int], rel_post_lines: set[int],
                          pre_method: Method, post_method: Method,
                          pre_post_line_map: dict[int, int], post_pre_line_map: dict[int, int],
                          pre_target_line_map: dict[int, int],
                          method_dir: str) -> tuple[str, str, str, set[int], set[int], str, str]:
    file_suffix = pre_method.file_suffix
    pre_context_lines = rel_pre_lines - pre_method.rel_diff_lines
    post_context_lines = rel_post_lines - post_method.rel_diff_lines
    for line in pre_context_lines:
        if line not in pre_post_line_map:
            continue
        post_context_lines.add(pre_post_line_map[line])
    for line in post_context_lines:
        if line not in post_pre_line_map:
            continue
        pre_context_lines.add(post_pre_line_map[line])
    pre_patchbp_lines = pre_context_lines | pre_method.rel_diff_lines
    post_patchbp_lines = post_context_lines | post_method.rel_diff_lines

    pre_patchbp_code_lines = [pre_method.rel_lines[line] for line in sorted(pre_patchbp_lines)]
    post_patchbp_codes_lines = [post_method.rel_lines[line] for line in sorted(post_patchbp_lines)]
    pre_sliced_code = pre_method.code_by_lines(pre_patchbp_lines)
    post_sliced_code = post_method.code_by_lines(post_patchbp_lines)
    pre_sliced_code_placeholder = pre_method.code_by_lines(pre_patchbp_lines, placeholder=config.PLACE_HOLDER)
    post_sliced_code_placeholder = post_method.code_by_lines(post_patchbp_lines, placeholder=config.PLACE_HOLDER)
    pre_sliced_code_placeholder_lines = pre_sliced_code_placeholder.split("\n")
    post_sliced_code_placeholder_lines = post_sliced_code_placeholder.split("\n")
    os.makedirs(method_dir, exist_ok=True)
    utils.write2file(os.path.join(method_dir, f"1.pre@s{file_suffix}"), pre_sliced_code)
    utils.write2file(os.path.join(method_dir, f"2.post@s{file_suffix}"), post_sliced_code)
    utils.write2file(os.path.join(method_dir, f"1.pre@sp{file_suffix}"), pre_sliced_code_placeholder)
    utils.write2file(os.path.join(method_dir, f"2.post@sp{file_suffix}"), post_sliced_code_placeholder)
    patch = '\n'.join(difflib.unified_diff(pre_sliced_code_placeholder_lines, post_sliced_code_placeholder_lines,
                                           fromfile="pre@s", tofile="post@s", lineterm="", n=10000))
    patch = '\n'.join(patch.split('\n')[3:])
    utils.write2file(os.path.join(method_dir, "patch.diff"), patch)
    return patch, pre_sliced_code, post_sliced_code, pre_patchbp_lines, post_patchbp_lines, pre_sliced_code_placeholder, post_sliced_code_placeholder


def target_method_slice(pre_method: Method, target_method: Method,
                        pre_patchbp_lines: set[int], pre_target_line_map: dict[int, int],
                        pre_target_hunk_map: dict[tuple[int, int], tuple[int, int]],
                        method_dir: str) -> tuple[set[int], str, str]:
    target_slice_rel_lines = set()
    for line in pre_patchbp_lines:
        if line in pre_target_line_map:
            target_slice_rel_lines.add(pre_target_line_map[line])
        else:
            for pre_hunk, target_hunk in pre_target_hunk_map.items():
                pre_hunk_start_line, pre_hunk_end_line = pre_hunk
                target_hunk_start_line, target_hunk_end_line = target_hunk
                if pre_hunk_start_line <= line <= pre_hunk_end_line:
                    target_slice_rel_lines.update(range(target_hunk_start_line, target_hunk_end_line + 1))
                    break
    if format.normalize(pre_method.code) != format.normalize(target_method.code):
        ast = ASTParser(target_method.code, target_method.language)
        if target_method.language == Language.C:
            body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
            if body_node is not None:
                target_slice_rel_lines = target_method.ast_add(ast, body_node, target_slice_rel_lines)

        if target_method.language == Language.JAVA:
            body_node = ast.query_oneshot("(method_declaration body: (block)@body)")
            if body_node is not None:
                target_slice_rel_lines = target_method.ast_dive_java(body_node, target_slice_rel_lines)
        elif target_method.language == Language.C:
            body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
            if body_node is not None:
                target_slice_rel_lines = target_method.ast_dive_c(body_node, target_slice_rel_lines)

    vulcode = target_method.code_by_lines(target_slice_rel_lines)
    vulcode_with_placeholder = target_method.code_by_lines(target_slice_rel_lines, placeholder=config.PLACE_HOLDER)
    file_suffix = target_method.file_suffix
    utils.write2file(os.path.join(method_dir, f"3.target@s{file_suffix}"), vulcode)
    utils.write2file(os.path.join(method_dir, f"3.target@sp{file_suffix}"), vulcode_with_placeholder)
    return target_slice_rel_lines, vulcode, vulcode_with_placeholder


def transplant_hunks(target_method: Method, target_slice_lines: set[int]) -> str:
    method_dir = target_method.method_dir
    assert method_dir is not None
    file_suffix = target_method.file_suffix

    with open(f"{method_dir}/2.post@sp{file_suffix}", "r") as f:
        post_sp = f.read()
        f.seek(0)
        post_sp_lines = f.readlines()
    with open(f"{method_dir}/3.target@sp{file_suffix}", "r") as f:
        target_sp = f.read()
        f.seek(0)
        target_sp_lines = f.readlines()
    post_target_line_map, post_target_hunk_map, diff_add_lines, diff_del_lines = hunkmap.code_map(post_sp, target_sp)
    target_post_line_map = {v: k for k, v in post_target_line_map.items()}
    for add_line in sorted(diff_add_lines, reverse=True):
        if target_sp_lines[add_line - 1].strip() == config.PLACE_HOLDER.strip():
            post_sp_lines.insert(target_post_line_map[add_line - 1], config.PLACE_HOLDER + "\n")

    post_target_line_map, post_target_hunk_map, _, _ = hunkmap.code_map("".join(post_sp_lines), target_sp)
    target_post_line_map = {v: k for k, v in post_target_line_map.items()}
    for post_hunk, target_hunk in post_target_hunk_map.items():
        post_hunk_start, post_hunk_end = post_hunk
        target_hunk_start, target_hunk_end = target_hunk
        if target_hunk_end - target_hunk_start == 0:
            if target_sp_lines[target_hunk_end - 1].strip() == config.PLACE_HOLDER.strip():
                post_sp_lines.insert(post_hunk_start - 1, config.PLACE_HOLDER + "\n")

    target_reduced_hunks = target_method.reduced_hunks(target_slice_lines)

    post_sp_placeholder_index = [i for i, line in enumerate(
        post_sp_lines) if line.strip() == config.PLACE_HOLDER.strip()]

    if len(post_sp_placeholder_index) != len(target_reduced_hunks):
        return ""

    ours_ag = post_sp_lines.copy()
    for i, hunk in enumerate(target_reduced_hunks):
        ours_ag[post_sp_placeholder_index[i]] = hunk

    ours_ag = "".join(ours_ag)
    utils.write2file(os.path.join(method_dir, f"5.ours@ag{file_suffix}"), ours_ag)
    return ours_ag


def bp_java(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False, slice_level: int = config.SLICE_LEVEL) -> dict[str, str | list[int]]:
    start_time = time.time()
    origin_before_func_code = patch["origin_before_func_code"]
    origin_after_func_code = patch["origin_after_func_code"]
    target_before_func_code = patch["target_before_func_code"]
    target_after_func_code = patch["target_after_func_code"]
    origin_before_file_code = patch["origin_before_file_code"]
    origin_after_file_code = patch["origin_after_file_code"]
    target_before_file_code = patch["target_before_file_code"]
    target_after_file_code = patch["target_after_file_code"]
    origin_before_func_signature = patch["origin_before_func_signature"]
    origin_after_func_signature = patch["origin_after_func_signature"]
    target_before_func_signature = patch["target_before_func_signature"]
    target_after_func_signature = patch["target_after_func_signature"]
    bptype = "SAME" if format.normalize(origin_before_func_code) == format.normalize(
        target_before_func_code) else "DIFF"
    results: dict[str, str | list[int]] = {
        "cveid": cveid,
        "file_path": file_path,
        "method_name": method_name,
        "bptype": bptype
    }

    file_name = os.path.basename(file_path)
    file_path_md5 = hashlib.md5(file_path.encode()).hexdigest()[:4]
    cache_dir = f"cache_java/{cveid}/{file_name}#{method_name}#{file_path_md5}"
    file_suffix = ".java" if language == Language.JAVA else ".c"
    os.makedirs(cache_dir, exist_ok=True)
    pre_dir = os.path.join(cache_dir, "pre")
    post_dir = os.path.join(cache_dir, "post")
    target_dir = os.path.join(cache_dir, "target")
    gt_dir = os.path.join(cache_dir, "gt")

    pre_codefile = CodeFile(file_path, origin_before_file_code)
    post_codefile = CodeFile(file_path, origin_after_file_code)
    target_codefile = CodeFile(file_path, target_before_file_code)
    gt_codefile = CodeFile(file_path, target_after_file_code)
    create_code_tree([pre_codefile], pre_dir, overwrite=overwrite)
    create_code_tree([post_codefile], post_dir, overwrite=overwrite)
    create_code_tree([target_codefile], target_dir, overwrite=overwrite)
    create_code_tree([gt_codefile], gt_dir, overwrite=overwrite)

    try:
        utils.export_joern_graph(pre_dir, post_dir, target_dir, need_cdg=False,
                                 language=language, multiprocess=False, overwrite=overwrite)
    except Exception as e:
        print(e)
        results["error"] = ErrorCode.JOERN_ERROR.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    try:
        pre_project = Project("1.pre", [pre_codefile], language)
        post_project = Project("2.post", [post_codefile], language)
        target_project = Project("3.target", [target_codefile], language)
        gt_project = Project("4.gt", [gt_codefile], language)
    except AssertionError:
        results["error"] = ErrorCode.AST_ERROR.value
        return results
    triple_projects = (pre_project, post_project, target_project)

    pre_project.load_joern_graph(f"{pre_dir}/cpg", f"{pre_dir}/pdg")
    post_project.load_joern_graph(f"{post_dir}/cpg", f"{post_dir}/pdg")
    target_project.load_joern_graph(f"{target_dir}/cpg", f"{target_dir}/pdg")

    file_name = file_path.split("/")[-1]
    triple_signature = (origin_before_func_signature, origin_after_func_signature, target_before_func_signature)
    triple_methods = Project.get_triple_methods_java(triple_projects, triple_signature)
    if triple_methods is None:
        results["error"] = ErrorCode.METHOD_NOT_FOUND.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    pre_method, post_method, target_method = triple_methods
    gt_method = gt_project.get_method(target_after_func_signature)
    if gt_method is None:
        gt_method = gt_project.get_method(post_method.signature)
    assert gt_method is not None
    assert pre_method is not None
    assert post_method is not None
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method
    target_method.counterpart = gt_method
    gt_method.counterpart = target_method

    if pre_method.pdg is None or post_method.pdg is None or target_method.pdg is None:
        results["error"] = ErrorCode.PDG_NOT_FOUND.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results

    method_dir = Method.init_method_dir(triple_methods, cache_dir, slice_level, gt_method)
    pre_post_line_map, pre_post_hunk_map, pre_post_add_lines, re_post_del_lines = hunkmap.method_map(
        pre_method, post_method)
    pre_target_line_map, pre_target_hunk_map, pre_target_add_lines, pre_target_del_lines = hunkmap.method_map(
        pre_method, target_method)
    post_target_line_map, post_target_hunk_map, post_target_add_lines, post_target_del_lines = hunkmap.method_map(
        post_method, target_method)
    post_pre_line_map = {v: k for k, v in pre_post_line_map.items()}

    backward_slice_level = slice_level
    forward_slice_level = slice_level
    try:
        pre_slice_results = pre_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
        post_slice_results = post_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    except KeyError:
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["error"] = ErrorCode.SLICE_FAILED.value
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    if pre_slice_results is None or post_slice_results is None:
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["error"] = ErrorCode.SLICE_FAILED.value
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    rel_pre_lines = pre_slice_results[1]
    rel_post_lines = post_slice_results[1]

    slice_results = sematic_enhance_patch(
        rel_pre_lines, rel_post_lines,
        pre_method, post_method,
        pre_post_line_map, post_pre_line_map,
        pre_target_line_map, method_dir)
    patch_code, pre_sliced_code, post_sliced_code, pre_sliced_lines, post_sliced_lines, pre_sliced_code_placeholder, post_sliced_code_placeholder = slice_results
    results["patch"] = patch_code
    results["pre_sliced_code"] = pre_sliced_code
    results["post_sliced_code"] = post_sliced_code
    results["pre_sliced_code_placeholder"] = pre_sliced_code_placeholder
    results["post_sliced_code_placeholder"] = post_sliced_code_placeholder

    target_slice_lines, target_sliced_code, target_sliced_code_placeholder = target_method_slice(
        pre_method, target_method, pre_sliced_lines, pre_target_line_map, pre_target_hunk_map, method_dir)
    results["target"] = target_sliced_code_placeholder

    if format.normalize(pre_sliced_code) == format.normalize(target_sliced_code):
        results["slice_type"] = "SAME"
        try:
            ours_ag = transplant_hunks(target_method, target_slice_lines)
        except:
            ours_ag = ""
        if ours_ag == "":
            results["ours_ag"] = "PLACEHOLDER_FAILED"
        elif format.normalize(ours_ag) == format.normalize(gt_method.code):
            results["ours_ag"] = "SUCCESS"
        else:
            results["ours_ag"] = "FAILED"
    else:
        results["slice_type"] = "DIFF"

    gt_code = gt_method.code
    diff_hunk = difftools.get_patch_hunks(target_method.code, gt_code)
    add_hunk = [hunk for hunk in diff_hunk if isinstance(hunk, difftools.AddHunk)]
    add_hunk.sort(key=lambda x: x.b_startline, reverse=True)
    for hunk in add_hunk:
        offset = utils.line2offset(gt_code, hunk.b_startline)
        gt_code = gt_code[:offset] + \
            gt_code[offset:].replace(hunk.b_code, "/*<<<GT-HUNK>>>*/", 1)

    use_new_method = False
    tmp_gt_code = gt_code
    for hunk in target_method.reduced_hunks(target_slice_lines):
        pos = gt_code.rfind(config.PLACE_HOLDER)
        pos = 0 if pos == -1 else pos
        if gt_code.find(hunk, pos) != -1:
            gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
        else:
            lines = [line.replace(" " * 4, "", 1) for line in hunk.split("\n")]
            hunk = "\n".join(lines)
            if gt_code.find(hunk, pos) != -1:
                gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
            else:
                use_new_method = True
                break
    if use_new_method:
        gt_code = tmp_gt_code.replace(" " * 4, "")
        for hunk in target_method.reduced_hunks(target_slice_lines):
            hunk = hunk.replace(" " * 4, "")
            pos = gt_code.rfind(config.PLACE_HOLDER)
            pos = 0 if pos == -1 else pos
            if gt_code.find(hunk, pos) != -1:
                gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
            else:
                results["error"] = ErrorCode.GROUNDTRUTH_SLICE_FAILED.value
                diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
                results["pre_sliced_code"] = origin_before_func_code
                results["post_sliced_code"] = origin_after_func_code
                results["patch"] = '\n'.join(diff.split('\n')[1:])
                results["target"] = target_before_func_code
                results["groundtruth"] = target_after_func_code
                return results

    add_hunk.sort(key=lambda x: x.b_startline)
    for hunk in add_hunk:
        gt_code = gt_code.replace("/*<<<GT-HUNK>>>*/", hunk.b_code, 1)

    if use_new_method:
        gt_code = format.astyle(gt_code)
        gt_code_lines = gt_code.split("\n")
        final_gt_code_lines = []
        for line in gt_code_lines:
            if line.strip() == config.PLACE_HOLDER.strip():
                final_gt_code_lines.append(config.PLACE_HOLDER)
            else:
                final_gt_code_lines.append(line)
        gt_code = "\n".join(final_gt_code_lines)

    utils.write2file(os.path.join(method_dir, f"4.gt@sp{file_suffix}"), gt_code)
    utils.method_diff2html(method_dir, file_suffix)

    results["error"] = ErrorCode.SUCCESS.value
    results["groundtruth"] = gt_code
    results["target_slice_lines"] = list(target_slice_lines)
    results["time"] = f"{(time.time() - start_time):.2f}"
    return results


def bp(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False, slice_level: int = config.SLICE_LEVEL) -> dict[str, str | list[int]]:
    start_time = time.time()
    origin_before_func_code = patch["origin_before_func_code"]
    origin_after_func_code = patch["origin_after_func_code"]
    target_before_func_code = patch["target_before_func_code"]
    target_after_func_code = patch["target_after_func_code"]
    bptype = "SAME" if format.normalize(origin_before_func_code) == format.normalize(
        target_before_func_code) else "DIFF"
    results: dict[str, str | list[int]] = {
        "cveid": cveid,
        "file_path": file_path,
        "method_name": method_name,
        "bptype": bptype
    }

    file_name = os.path.basename(file_path)
    file_path_md5 = hashlib.md5(file_path.encode()).hexdigest()[:4]
    cache_dir = f"cache_bug/{cveid}/{file_name}#{method_name}#{file_path_md5}"
    file_suffix = ".java" if language == Language.JAVA else ".c"
    os.makedirs(cache_dir, exist_ok=True)
    pre_dir = os.path.join(cache_dir, "pre")
    post_dir = os.path.join(cache_dir, "post")
    target_dir = os.path.join(cache_dir, "target")
    gt_dir = os.path.join(cache_dir, "gt")

    pre_codefile = CodeFile(file_path, origin_before_func_code)
    post_codefile = CodeFile(file_path, origin_after_func_code)
    target_codefile = CodeFile(file_path, target_before_func_code)
    gt_codefile = CodeFile(file_path, target_after_func_code)
    create_code_tree([pre_codefile], pre_dir, overwrite=overwrite)
    create_code_tree([post_codefile], post_dir, overwrite=overwrite)
    create_code_tree([target_codefile], target_dir, overwrite=overwrite)
    create_code_tree([gt_codefile], gt_dir, overwrite=overwrite)

    try:
        utils.export_joern_graph(pre_dir, post_dir, target_dir, need_cdg=False,
                                 language=language, multiprocess=False, overwrite=overwrite)
    except:
        results["error"] = ErrorCode.JOERN_ERROR.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    try:
        pre_project = Project("1.pre", [pre_codefile], language)
        post_project = Project("2.post", [post_codefile], language)
        target_project = Project("3.target", [target_codefile], language)
        gt_project = Project("4.gt", [gt_codefile], language)
    except AssertionError:
        results["error"] = ErrorCode.AST_ERROR.value
        return results
    triple_projects = (pre_project, post_project, target_project)

    pre_project.load_joern_graph(f"{pre_dir}/cpg", f"{pre_dir}/pdg")
    post_project.load_joern_graph(f"{post_dir}/cpg", f"{post_dir}/pdg")
    target_project.load_joern_graph(f"{target_dir}/cpg", f"{target_dir}/pdg")

    file_name = file_path.split("/")[-1]
    method_signature = f"{file_name}#{method_name}"
    triple_methods = Project.get_triple_methods(triple_projects, method_signature)
    if triple_methods is None:
        results["error"] = ErrorCode.METHOD_NOT_FOUND.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    pre_method, post_method, target_method = triple_methods
    gt_method = gt_project.get_method(method_signature)
    if gt_method is None:
        gt_method = gt_project.get_method(post_method.signature)
    assert gt_method is not None
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method
    target_method.counterpart = gt_method
    gt_method.counterpart = target_method

    if pre_method.pdg is None or post_method.pdg is None or target_method.pdg is None:
        results["error"] = ErrorCode.PDG_NOT_FOUND.value
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results

    method_dir = Method.init_method_dir(triple_methods, cache_dir, slice_level, gt_method)
    pre_post_line_map, pre_post_hunk_map, pre_post_add_lines, re_post_del_lines = hunkmap.method_map(
        pre_method, post_method)
    pre_target_line_map, pre_target_hunk_map, pre_target_add_lines, pre_target_del_lines = hunkmap.method_map(
        pre_method, target_method)
    post_target_line_map, post_target_hunk_map, post_target_add_lines, post_target_del_lines = hunkmap.method_map(
        post_method, target_method)
    post_pre_line_map = {v: k for k, v in pre_post_line_map.items()}

    backward_slice_level = slice_level
    forward_slice_level = slice_level
    try:
        pre_slice_results = pre_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
        post_slice_results = post_method.slice_by_diff_lines(backward_slice_level, forward_slice_level, write_dot=True)
    except KeyError:
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["error"] = ErrorCode.SLICE_FAILED.value
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    if pre_slice_results is None or post_slice_results is None:
        diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
        results["error"] = ErrorCode.SLICE_FAILED.value
        results["pre_sliced_code"] = origin_before_func_code
        results["post_sliced_code"] = origin_after_func_code
        results["patch"] = '\n'.join(diff.split('\n')[1:])
        results["target"] = target_before_func_code
        results["groundtruth"] = target_after_func_code
        return results
    rel_pre_lines = pre_slice_results[1]
    rel_post_lines = post_slice_results[1]

    slice_results = sematic_enhance_patch(
        rel_pre_lines, rel_post_lines,
        pre_method, post_method,
        pre_post_line_map, post_pre_line_map,
        pre_target_line_map, method_dir)
    patch_code, pre_sliced_code, post_sliced_code, pre_sliced_lines, post_sliced_lines, pre_sliced_code_placeholder, post_sliced_code_placeholder = slice_results
    results["patch"] = patch_code
    results["pre_sliced_code"] = pre_sliced_code
    results["post_sliced_code"] = post_sliced_code
    results["pre_sliced_code_placeholder"] = pre_sliced_code_placeholder
    results["post_sliced_code_placeholder"] = post_sliced_code_placeholder

    target_slice_lines, target_sliced_code, target_sliced_code_placeholder = target_method_slice(
        pre_method, target_method, pre_sliced_lines, pre_target_line_map, pre_target_hunk_map, method_dir)
    results["target"] = target_sliced_code_placeholder

    if format.normalize(pre_sliced_code) == format.normalize(target_sliced_code):
        results["slice_type"] = "SAME"
        try:
            ours_ag = transplant_hunks(target_method, target_slice_lines)
        except:
            ours_ag = ""
        if ours_ag == "":
            results["ours_ag"] = "PLACEHOLDER_FAILED"
        elif format.normalize(ours_ag) == format.normalize(gt_method.code):
            results["ours_ag"] = "SUCCESS"
        else:
            results["ours_ag"] = "FAILED"
    else:
        results["slice_type"] = "DIFF"

    gt_code = gt_method.code
    diff_hunk = difftools.get_patch_hunks(target_method.code, gt_code)
    add_hunk = [hunk for hunk in diff_hunk if isinstance(hunk, difftools.AddHunk)]
    add_hunk.sort(key=lambda x: x.b_startline, reverse=True)
    for hunk in add_hunk:
        offset = utils.line2offset(gt_code, hunk.b_startline)
        gt_code = gt_code[:offset] + \
            gt_code[offset:].replace(hunk.b_code, "/*<<<GT-HUNK>>>*/", 1)

    use_new_method = False
    tmp_gt_code = gt_code
    for hunk in target_method.reduced_hunks(target_slice_lines):
        pos = gt_code.rfind(config.PLACE_HOLDER)
        pos = 0 if pos == -1 else pos
        if gt_code.find(hunk, pos) != -1:
            gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
        else:
            lines = [line.replace(" " * 4, "", 1) for line in hunk.split("\n")]
            hunk = "\n".join(lines)
            if gt_code.find(hunk, pos) != -1:
                gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
            else:
                use_new_method = True
                break
    if use_new_method:
        gt_code = tmp_gt_code.replace(" " * 4, "")
        for hunk in target_method.reduced_hunks(target_slice_lines):
            hunk = hunk.replace(" " * 4, "")
            pos = gt_code.rfind(config.PLACE_HOLDER)
            pos = 0 if pos == -1 else pos
            if gt_code.find(hunk, pos) != -1:
                gt_code = gt_code[:pos] + gt_code[pos:].replace(hunk, config.PLACE_HOLDER + "\n", 1)
            else:
                results["error"] = ErrorCode.GROUNDTRUTH_SLICE_FAILED.value
                diff = difftools.git_diff_code(origin_before_func_code, origin_after_func_code, remove_diff_header=True)
                results["pre_sliced_code"] = origin_before_func_code
                results["post_sliced_code"] = origin_after_func_code
                results["patch"] = '\n'.join(diff.split('\n')[1:])
                results["target"] = target_before_func_code
                results["groundtruth"] = target_after_func_code
                return results

    add_hunk.sort(key=lambda x: x.b_startline)
    for hunk in add_hunk:
        gt_code = gt_code.replace("/*<<<GT-HUNK>>>*/", hunk.b_code, 1)

    if use_new_method:
        gt_code = format.astyle(gt_code)
        gt_code_lines = gt_code.split("\n")
        final_gt_code_lines = []
        for line in gt_code_lines:
            if line.strip() == config.PLACE_HOLDER.strip():
                final_gt_code_lines.append(config.PLACE_HOLDER)
            else:
                final_gt_code_lines.append(line)
        gt_code = "\n".join(final_gt_code_lines)

    utils.write2file(os.path.join(method_dir, f"4.gt@sp{file_suffix}"), gt_code)
    utils.method_diff2html(method_dir, file_suffix)

    results["error"] = ErrorCode.SUCCESS.value
    results["groundtruth"] = gt_code
    results["target_slice_lines"] = list(target_slice_lines)
    results["time"] = f"{(time.time() - start_time):.2f}"

    fixed_code = llm.llm_fix(patch_code, target_sliced_code_placeholder, language)
    if fixed_code is None:
        return ()
    utils.write2file(os.path.join(method_dir, f"5.ours@sp{file_suffix}"), fixed_code)
    final_code = target_method.recover_placeholder(fixed_code, target_slice_lines, config.PLACE_HOLDER)
    if final_code is None:
        return ()
    else:
        utils.write2file(os.path.join(method_dir, f"5.ours{file_suffix}"), final_code)


def bp_warper(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False, slice_level: int = config.SLICE_LEVEL) -> dict[str, str | list[int]]:
    try:
        return bp(cveid, patch, file_path, method_name, language, overwrite, slice_level)
    except Exception as e:
        return {
            "cveid": cveid,
            "file_path": file_path,
            "method_name": method_name,
            "error": ErrorCode.EXCEPTION.value
        }


def bp_java_warper(cveid: str, patch: dict[str, str], file_path: str, method_name: str, language: Language, overwrite: bool = False, slice_level: int = config.SLICE_LEVEL) -> dict[str, str | list[int]]:
    try:
        return bp_java(cveid, patch, file_path, method_name, language, overwrite, slice_level)
    except Exception as e:
        return {
            "cveid": cveid,
            "file_path": file_path,
            "method_name": method_name,
            "error": ErrorCode.EXCEPTION.value
        }


def load_info(cveid: str, cve_info: dict):
    info = {}
    patch: dict = cve_info["patch"]
    for p in patch:
        file_path = p.split("#")[0]
        method_name = p.split("#")[1]
        info[cveid + "#" + file_path + "#" + method_name] = {
            "origin_before": format.format(patch[p]["origin_before_func_code"], Language.C, True, True),
            "origin_after": format.format(patch[p]["origin_after_func_code"], Language.C, True, True),
            "target_before": format.format(patch[p]["target_before_func_code"], Language.C, True, True),
            "target_after": format.format(patch[p]["target_after_func_code"], Language.C, True, True)
        }
    return info


def init_infos(data: dict) -> dict:
    infos: dict[str, dict] = {}
    load_info_args = []
    for cveid, info in data.items():
        load_info_args.append((cveid, info))
    init_infos: list[dict] = cpu_heater.multiprocess(load_info_args, load_info, show_progress=True)
    for info in init_infos:
        infos.update(info)
    return infos


def generate_finetune_data(infos: dict, slice_level: int):
    finetune = {}
    error_states: dict[str, int] = {error.value: 0 for error in ErrorCode}
    cveid_set = set()
    for key, val in infos.items():
        if "error" not in val:
            continue
        if val["error"] != ErrorCode.SUCCESS.value:
            error_states[val["error"]] += 1
        cveid = val["cveid"]
        cveid_set.add(cveid)
        file_path = val["file_path"]
        method_name = val["method_name"]
        bptype = val.get("bptype", "")
        slice_type = val.get("slice_type", "")
        patch = val["patch"]
        target = val["target"]
        groundtruth = val["groundtruth"]
        finetune[key] = {
            "cveid": cveid,
            "file_path": file_path,
            "method_name": method_name,
            "bptype": bptype,
            "slice_type": slice_type,
            "patch": patch,
            "target": target,
            "groundtruth": groundtruth
        }
    with open(f"finetune#{slice_level}.json", "w") as f:
        json.dump(finetune, f, indent=4)
    print(f"Total data: {len(infos)}")
    print(f"Finetune data generated: {len(finetune)}")
    print(f"Finetune cve generated: {len(cveid_set)}")
    print(f"Error states: {error_states}")


def batch_run_multiprocess(json_data: str, max_workers: int, slice_level: int = config.SLICE_LEVEL, overwrite: bool = False):
    with open(json_data, "r") as f:
        data: dict = json.load(f)

    infos: dict[str, dict] = init_infos(data)
    args_list = []
    for cveid, info in data.items():
        for pk, pv in info["patch"].items():
            file_path = pk.split("#")[0]
            method_name = pk.split("#")[1]
            args_list.append((cveid, pv, file_path, method_name, Language.C, overwrite, slice_level))
    results = cpu_heater.multiprocess(args_list, bp_warper, max_workers=max_workers, show_progress=True)
    for result in results:
        cveid = result["cveid"]
        file_path = result["file_path"]
        method_name = result["method_name"]
        key = cveid + "#" + file_path + "#" + method_name
        if key in infos:
            infos[key].update(result)
    with open(f"info#{slice_level}.json", "w") as f:
        json.dump(infos, f, indent=4, sort_keys=True)
    generate_finetune_data(infos, slice_level)


def batch_run_multiprocess_java(json_data: str, max_workers: int, slice_level: int = config.SLICE_LEVEL, overwrite: bool = False):
    with open(json_data, "r") as f:
        data: dict = json.load(f)

    infos: dict[str, dict] = init_infos(data)
    args_list = []
    for cveid, info in data.items():
        for pk, pv in info["patch"].items():
            file_path = pk.split("#")[0]
            method_name = pk.split("#")[1]
            args_list.append((cveid, pv, file_path, method_name, Language.JAVA, overwrite, slice_level))
    results = cpu_heater.multiprocess(args_list, bp_java_warper, max_workers=max_workers, show_progress=True)
    for result in results:
        temp_result = result
        cveid = result["cveid"]
        file_path = result["file_path"]
        method_name = result["method_name"]
        if result["error"] != ErrorCode.SUCCESS.value:
            file_name = os.path.basename(file_path)
            file_path_md5 = hashlib.md5(file_path.encode()).hexdigest()[:4]
            cache_dir = f"cache_java/{cveid}/{file_name}#{method_name}#{file_path_md5}"
            os.system(f"rm -r {cache_dir}")
            results = single_cve_debug_java(json_data, cveid, result["file_path"], result["method_name"])
            temp_result = results[0]
        key = cveid + "#" + file_path + "#" + method_name
        if key in infos:
            infos[key].update(temp_result)
    with open(f"info#{slice_level}.json", "w") as f:
        json.dump(infos, f, indent=4, sort_keys=True)
    generate_finetune_data(infos, slice_level)


def batch_run_multiprocess_level(json_data: str, max_workers: int):
    for i in range(6):
        config.SLICE_LEVEL = i
        batch_run_multiprocess(json_data, max_workers, config.SLICE_LEVEL)


def batch_run(json_data: str, slice_level: int = config.SLICE_LEVEL):
    with open(json_data, "r") as f:
        data: dict = json.load(f)

    infos: dict[str, dict] = init_infos(data)
    for cveid, info in data.items():
        for pk, pv in info["patch"].items():
            file_path = pk.split("#")[0]
            method_name = pk.split("#")[1]
            key = cveid + "#" + file_path + "#" + method_name
            result = bp(cveid, pv, file_path, method_name, Language.C, overwrite=False)
            if key in infos:
                infos[key].update(result)
    with open(f"info#{config.SLICE_LEVEL}.json", "w") as f:
        json.dump(infos, f, indent=4, sort_keys=True)
    generate_finetune_data(infos, slice_level)


def single_cve_debug(json_data: str, cveid: str):
    log.init_logger(logging.getLogger(), logging.DEBUG, "log.log")
    with open(json_data, "r") as f:
        data: dict = json.load(f)
    for pk, pv in data[cveid]["patch"].items():
        file_path = pk.split("#")[0]
        method_name = pk.split("#")[1]
        result = bp(cveid, pv, file_path, method_name, Language.C, overwrite=False)
        print(result["cveid"], result["file_path"], result["method_name"],
              result["error"], result["bptype"])
        if result["error"] == ErrorCode.SUCCESS.value:
            print("time:", result["time"])
        if "ours_ag" in result:
            print("ours_ag", result["ours_ag"])


def single_cve_debug_java(json_data: str, cveid: str, file_path_raw: str, method_name_raw: str):
    results = []
    log.init_logger(logging.getLogger(), logging.DEBUG, "log.log")
    with open(json_data, "r") as f:
        data: dict = json.load(f)
    for pk, pv in data[cveid]["patch"].items():
        file_path = pk.split("#")[0]
        method_name = pk.split("#")[1]
        if file_path != file_path_raw and method_name != method_name_raw:
            continue
        result = bp_java(cveid, pv, file_path, method_name, Language.JAVA, overwrite=False)
        print(result["cveid"], result["file_path"], result["method_name"],
              result["error"], result["bptype"])
        if result["error"] == ErrorCode.SUCCESS.value:
            print("time:", result["time"])
        if "ours_ag" in result:
            print("ours_ag", result["ours_ag"])
        results.append(result)
    return results
