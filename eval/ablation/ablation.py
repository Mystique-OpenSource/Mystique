import json
import os

import cpu_heater
from cb import calc_codebleu

import config
import difftools
from common import BPType, Language, Metric
from llm import clean_llm_output
from utils import exact_match


def evaluate_worker(tool: str, key: str, val: dict, info: dict, output_path: str):
    if key not in info:
        print(f"Not found {key}")
        return

    py_sp: str = val[tool]
    py: str = val.get(f"{tool}_recover", "")
    py_sp = clean_llm_output(py_sp, Language.C)
    pa = info[key]["origin_before"]
    pb = info[key]["origin_after"]
    px = info[key]["target_before"]
    pg = info[key]["target_after"]
    pg_sp: str = info[key]["groundtruth"]
    pg_s = ""
    for line in pg_sp.split("\n"):
        if line.strip() != config.PLACE_HOLDER.strip():
            pg_s += line + "\n"

    px_sp = info[key]["target"]
    pa_s = info[key]["pre_sliced_code"]
    pb_s = info[key]["post_sliced_code"]
    pa_sp = info[key].get("pre_sliced_code_placeholder", "")
    pb_sp = info[key].get("post_sliced_code_placeholder", "")
    bptype = BPType.SAME if info[key]["bptype"] == BPType.SAME.value else BPType.DIFF

    is_exact_match = exact_match(py_sp, pg_sp)
    status = Metric.EM.value if is_exact_match else Metric.NOT_EM.value

    key_name = key.replace("/", ".")
    path = f"./{output_path}/{status}/{bptype.value}/{key_name}"
    os.makedirs(path, exist_ok=True)
    difftools.diff2html_code(py_sp, pg_sp, os.path.join(
        path, "py@sp_pg@sp.html"), title="py@sp_pg@sp")
    difftools.diff2html_code(pa, px, os.path.join(
        path, "pa_px.html"), title="pa_px")
    difftools.diff2html_code(pb, pg, os.path.join(
        path, "pb_pg.html"), title="pb_pg")
    difftools.diff2html_code(pa, pb, os.path.join(
        path, "pa_pb.html"), title="pa_pb")
    difftools.diff2html_code(px, pg, os.path.join(
        path, "px_pg.html"), title="px_pg")
    difftools.diff2html_code(px, px_sp, os.path.join(
        path, "px_px@sp.html"), title="px_px@sp")
    difftools.diff2html_code(px_sp, py_sp, os.path.join(
        path, "px@sp_py@sp.html"), title="px@sp_py@sp")
    difftools.diff2html_code(py_sp, pb_s, os.path.join(
        path, "py@sp_pb@s.html"), title="py@sp_pb@s")
    difftools.diff2html_code(pa_s, pb_s, os.path.join(
        path, "pa@s_pb@s.html"), title="pa@s_pb@s")
    difftools.diff2html_code(pa_s, px_sp, os.path.join(
        path, "pa@s_px@sp.html"), title="pa@s_px@sp")
    difftools.diff2html_code(px_sp, pg_sp, os.path.join(
        path, "px@sp_pg@sp.html"), title="px@sp_pg@sp")
    difftools.diff2html_code(pg_s, pb_s, os.path.join(
        path, "pg@s_pb@s.html"), title="pg@s_pb@s")
    difftools.diff2html_code(py_sp, pb_sp, os.path.join(
        path, "py@sp_pb@sp.html"), title="py@sp_pb@sp")
    difftools.diff2html_code(py, pg, os.path.join(
        path, "py_pg.html"), title="py_pg")
    difftools.diff2html_code(py, pb, os.path.join(
        path, "py_pb.html"), title="py_pb")
    difftools.diff2html_code(px, py, os.path.join(
        path, "px_py.html"), title="px_py")


def inspect(tool: str, result_path: str, info_path: str, output_path: str):
    with open(result_path, "r") as f:
        llm_data = json.load(f)
    with open(info_path, "r") as f:
        info: dict = json.load(f)

    em_same_path = f"./{output_path}/{Metric.EM.value}/{BPType.SAME.value}"
    em_diff_path = f"./{output_path}/{Metric.EM.value}/{BPType.DIFF.value}"
    not_em_same_path = f"./{output_path}/{Metric.NOT_EM.value}/{BPType.SAME.value}"
    not_em_diff_path = f"./{output_path}/{Metric.NOT_EM.value}/{BPType.DIFF.value}"
    os.makedirs(em_same_path, exist_ok=True)
    os.makedirs(em_diff_path, exist_ok=True)
    os.makedirs(not_em_same_path, exist_ok=True)
    os.makedirs(not_em_diff_path, exist_ok=True)

    args = []
    for key, val in llm_data.items():
        args.append((tool, key, val, info, output_path))

    cpu_heater.multiprocess(evaluate_worker, args, show_progress=True)


def report(inspect_path: str, report_file: bool, refine: bool = False):
    em_same_path = os.path.join(inspect_path, Metric.EM.value, BPType.SAME.value)
    em_diff_path = os.path.join(inspect_path, Metric.EM.value, BPType.DIFF.value)
    not_em_same_path = os.path.join(inspect_path, Metric.NOT_EM.value, BPType.SAME.value)
    not_em_diff_path = os.path.join(inspect_path, Metric.NOT_EM.value, BPType.DIFF.value)

    total_cve_set = set()
    em_same_cve_set = set()
    em_diff_cve_set = set()
    not_em_same_cve_set = set()
    not_em_diff_cve_set = set()
    em_same_method = set()
    em_diff_method = set()
    not_em_same_method = set()
    not_em_diff_method = set()
    for key in os.listdir(em_same_path):
        cveid = key.split("#")[0]
        em_same_cve_set.add(cveid)
        em_same_method.add(key.replace(".", "/", key.count(".") - 1))
    for key in os.listdir(em_diff_path):
        cveid = key.split("#")[0]
        em_diff_cve_set.add(cveid)
        em_diff_method.add(key.replace(".", "/", key.count(".") - 1))
    for key in os.listdir(not_em_same_path):
        cveid = key.split("#")[0]
        not_em_same_cve_set.add(cveid)
        not_em_same_method.add(key.replace(".", "/", key.count(".") - 1))
    for key in os.listdir(not_em_diff_path):
        cveid = key.split("#")[0]
        not_em_diff_cve_set.add(cveid)
        not_em_diff_method.add(key.replace(".", "/", key.count(".") - 1))
    total_cve_set.update(em_same_cve_set)
    total_cve_set.update(em_diff_cve_set)
    total_cve_set.update(not_em_same_cve_set)
    total_cve_set.update(not_em_diff_cve_set)
    succ_cve_set = set(em_same_cve_set | em_diff_cve_set)
    fail_cve_set = set(not_em_same_cve_set | not_em_diff_cve_set)
    succ_cve_set -= fail_cve_set
    fail_cve_set = total_cve_set - succ_cve_set
    print(f"Total CVE: {len(total_cve_set)}")
    print(f"Succ CVE: {len(succ_cve_set)} ({len(succ_cve_set)/len(total_cve_set)})")
    print(f"Fail CVE: {len(fail_cve_set)} ({len(fail_cve_set)/len(total_cve_set)})")

    acc = {
        "em_cve": list(succ_cve_set),
        "not_em_cve": list(fail_cve_set),
        "em_method": list(em_same_method | em_diff_method),
        "not_em_method": list(not_em_same_method | not_em_diff_method),
        "em_same_method": list(em_same_method),
        "em_diff_method": list(em_diff_method),
        "not_em_same_method": list(not_em_same_method),
        "not_em_diff_method": list(not_em_diff_method),
    }
    if report_file:
        with open("acc.json", "w") as f:
            json.dump(acc, f, indent=4)

    em_same = len(os.listdir(em_same_path))
    not_em_same = len(os.listdir(not_em_same_path))
    em_diff = len(os.listdir(em_diff_path))
    not_em_diff = len(os.listdir(not_em_diff_path))
    total = em_same + not_em_same + em_diff + not_em_diff
    same = em_same + not_em_same
    diff = em_diff + not_em_diff
    em = em_same + em_diff
    not_em = not_em_same + not_em_diff
    print()
    print(f"Toal CVE Method: {em_same+not_em_same+em_diff+not_em_diff}")
    print(f"SAME: {same}, DIFF: {diff}")
    print(f"EM: {em}, NOT EM: {not_em}")
    print(f"SAME EM: {em_same}, DIFF EM: {em_diff}")
    if same != 0:
        print(f"SAME EM Rate: {em_same / same}")
    if diff != 0:
        print(f"DIFF EM Rate: {em_diff / diff}")
    print(f"EM Rate: {em / (total)}")
    return acc


def codebleu_evaluate(acc: dict[str, list[str]], result_path: str, info_path: str):
    with open(result_path, "r") as f:
        llm_data = json.load(f)
    with open(info_path, "r") as f:
        info: dict = json.load(f)

    failed_method = acc["not_em_method"]
    failed_cve = acc["not_em_cve"]
    print(f"Failed Function: {len(failed_method)}")
    print(f"Failed CVE: {len(failed_cve)}")
    method_codeblue_total_score = 0
    for key in failed_method:
        if key.startswith("CVE-2024-25940#usr/sbin") or key.startswith("CVE-2023-3494#usr/sbin"):
            key = key.replace("usr/sbin", "usr.sbin")
        if key not in llm_data:
            print(f"Not found {key}")
            continue
        val = llm_data[key]
        ours: str = val["our_tool"]
        ours = clean_llm_output(ours, Language.C)
        ground_truth: str = info[key]["groundtruth"]
        method_codeblue_total_score += calc_codebleu(ours, ground_truth, Language.C)
    print(f"Average Function CodeBLEU: {method_codeblue_total_score / len(failed_method)}")

    cve_codeblue_total_score = 0
    for key in failed_cve:
        k_v = []
        cve_codeblue_score = 0
        for k, v in llm_data.items():
            if k.split("#")[0] == key:
                k_v.append((k, v))
        for key, val in k_v:
            ours: str = val["our_tool"]
            ours = clean_llm_output(ours, Language.C)
            ground_truth: str = info[key]["groundtruth"]
            cve_codeblue_score += calc_codebleu(ours, ground_truth, Language.C)
        cve_codeblue_total_score += cve_codeblue_score / len(k_v)
    print(f"Average CVE CodeBLEU: {cve_codeblue_total_score / len(failed_cve)}")


def codellama(result_path: str, inspect_path: str, info_path: str, only_report: bool, report_file: bool):
    if not only_report:
        inspect("our_tool", result_path, info_path, inspect_path)
    acc = report(inspect_path, report_file)
    codebleu_evaluate(acc, result_path, info_path)


def noslice(only_report: bool):
    result_path = "./ablation/noslice/results.json"
    inspect_path = "inspect/codellama-ft-9/ablation/noslice"
    info_path = f"../2.Method/data/test/merge/info#1.json"
    codellama(result_path, inspect_path, info_path, only_report=only_report, report_file=True)


def noft(only_report: bool):
    result_path = "./ablation/noft/results.json"
    inspect_path = "inspect/codellama-ft-9/ablation/noft"
    info_path = f"../2.Method/data/test/merge/info#1.json"
    codellama(result_path, inspect_path, info_path, only_report=only_report, report_file=True)


def norf(only_report: bool):
    result_path = "./ablation/norf/results.json"
    inspect_path = "inspect/codellama-ft-9/ablation/norf"
    info_path = f"../2.Method/data/test/merge/info#1.json"
    codellama(result_path, inspect_path, info_path, only_report=only_report, report_file=True)
