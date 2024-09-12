import hashlib
import json
import os

import cpu_heater
from cb import calc_codebleu

import config
import difftools
from common import BPType, Language, Metric
from llm import clean_llm_output
from utils import exact_match


def evaluate_worker(tool: str, key: str, val: dict, info: dict, output_path: str, language: Language):
    if key not in info:
        print(f"Not found {key}")
        return

    py_sp: str = val[tool]
    if tool == "our_tool" or tool == "ppathf":
        py: str = val.get(f"{tool}_recover", "")
    else:
        py: str = val.get(tool, "")
    py_sp = clean_llm_output(py_sp, language)
    py: str = clean_llm_output(py, language)
    pa = info[key]["origin_before"]
    pb = info[key]["origin_after"]
    px = info[key]["target_before"]
    pg = info[key]["target_after"]
    pg_sp: str = info[key]["groundtruth"]
    if language == Language.JAVA:
        pg = pg.replace("@Override", "")
        pg_sp = pg_sp.replace("@Override", "")
        py = py.replace("@Override", "")
        py_sp = py_sp.replace("@Override", "")
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

    if tool == "our_tool":
        is_exact_match = exact_match(py_sp, pg_sp) or exact_match(py, pg)
    else:
        is_exact_match = exact_match(py, pg)
    status = Metric.EM.value if is_exact_match else Metric.NOT_EM.value

    key_name = key.replace("/", ".")
    # if language == Language.JAVA:
    #     key_name = key_name.split("#")[0] + "#" + key_name.split("#")[-1] + "#" + \
    #         hashlib.md5(key_name.encode()).hexdigest()[:4]
    if len(key_name) > 255:
        cveid = key_name.split("#")[0]
        method_name = key_name.split("#")[-1]
        key_name = f"{cveid}#{hashlib.md5(key_name.encode()).hexdigest()[:4]}#{method_name}"
    path = f"./{output_path}/{status}/{bptype.value}/{key_name}"
    os.makedirs(path, exist_ok=True)
    difftools.diff2html_code(py_sp, pg_sp, os.path.join(
        path, "py@sp_pg@sp.html"), title="py@sp_pg@sp")
    difftools.diff2html_code(pa, px, os.path.join(path, "pa_px.html"), title="pa_px")
    difftools.diff2html_code(pb, pg, os.path.join(path, "pb_pg.html"), title="pb_pg")
    difftools.diff2html_code(pa, pb, os.path.join(path, "pa_pb.html"), title="pa_pb")
    difftools.diff2html_code(px, pg, os.path.join(path, "px_pg.html"), title="px_pg")
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
    difftools.diff2html_code(py, pg, os.path.join(path, "py_pg.html"), title="py_pg")
    difftools.diff2html_code(py, pb, os.path.join(path, "py_pb.html"), title="py_pb")
    difftools.diff2html_code(px, py, os.path.join(path, "px_py.html"), title="px_py")
    difftools.diff2html_code(pb, pg, os.path.join(path, "pb_pg.html"), title="pb_pg")


def inspect(tool: str, result_path: str, info_path: str, output_path: str, language: Language):
    with open(result_path, "r") as f:
        results_data = json.load(f)
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
    for key, val in results_data.items():
        args.append((tool, key, val, info, output_path, language))

    cpu_heater.multiprocess(evaluate_worker, args, show_progress=True)


def report(inspect_path: str, report_file: bool):
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


def codebleu_evaluate(acc: dict[str, list[str]], result_path: str, info_path: str, language: Language, tool: str = "our_tool"):
    with open(result_path, "r") as f:
        llm_data = json.load(f)
    with open(info_path, "r") as f:
        info: dict = json.load(f)

    failed_method = acc["not_em_method"]
    failed_cve = acc["not_em_cve"]
    print(f"Failed Function: {len(failed_method)}")
    print(f"Failed CVE: {len(failed_cve)}")
    method_codeblue_total_score = 0
    total = 0
    for key in failed_method:
        if key.startswith("CVE-2024-25940#usr/sbin") or key.startswith("CVE-2023-3494#usr/sbin"):
            key = key.replace("usr/sbin", "usr.sbin")
        if key not in llm_data:
            continue
        total += 1
        val = llm_data[key]
        ours: str = val[tool]
        ours = clean_llm_output(ours, language)
        ground_truth: str = info[key]["groundtruth"]
        method_codeblue_total_score += calc_codebleu(ours, ground_truth, language)
    print(f"Average Function CodeBLEU: {method_codeblue_total_score / total}")
    return
    cve_codeblue_total_score = 0
    for key in failed_cve:
        k_v = []
        cve_codeblue_score = 0
        for k, v in llm_data.items():
            if k.split("#")[0] == key:
                k_v.append((k, v))
        for key, val in k_v:
            ours: str = val[tool]
            ours = clean_llm_output(ours, Language.C)
            ground_truth: str = info[key]["groundtruth"]
            cve_codeblue_score += calc_codebleu(ours, ground_truth, Language.C)
        cve_codeblue_total_score += cve_codeblue_score / len(k_v)
    print(f"Average CVE CodeBLEU: {cve_codeblue_total_score / len(failed_cve)}")


def evaluate(result_path: str, inspect_path: str, info_path: str, only_report: bool, report_file: bool, language: Language, tool: str = "our_tool"):
    if not only_report:
        inspect(tool, result_path, info_path, inspect_path, language)
    acc = report(inspect_path, report_file)
    codebleu_evaluate(acc, result_path, info_path, language, tool)


def ours_merge(tool: str, only_report: bool, report_file: bool, deep: int):
    result_path = f"./results/codellama-ft/{tool}/merge-cve#{deep}.json"
    info_path = f"../2.Method/data/test/merge/info#{deep}.json"
    inspect_path = f"inspect/codellama-ft/{tool}/merge-cve#{deep}"
    evaluate(result_path, inspect_path, info_path, only_report, report_file, Language.C)


def ours_linux(tool: str, only_report: bool, report_file: bool, deep: int):
    result_path = f"./results/codellama-ft/{tool}/linux-cve#{deep}.json"
    info_path = f"../2.Method/data/test/linux/info#{deep}.json"
    inspect_path = f"inspect/codellama-ft/{tool}/linux-cve#{deep}"
    evaluate(result_path, inspect_path, info_path, only_report, report_file, Language.C)


def ours_others(tool: str, only_report: bool, report_file: bool, deep: int):
    result_path = f"./results/codellama-ft/{tool}/others-cve#{deep}.json"
    info_path = f"../2.Method/data/test/others/info#{deep}.json"
    inspect_path = f"inspect/codellama-ft/{tool}/others-cve#{deep}"
    evaluate(result_path, inspect_path, info_path, only_report, report_file, Language.C)


def train_others_test_linux():
    result_path = "./results/codellama-ft/codellama-ft-9/train-others-test-linux.json"
    inspect_path = "inspect/codellama-ft/codellama-ft-9/train-others-test-linux"
    info_path = f"../2.Method/data/test/linux/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=True, report_file=True, language=Language.C)


def train_linux_test_others():
    result_path = "./results/codellama-ft/codellama-ft-9/train-linux-test-others.json"
    inspect_path = "inspect/codellama-ft/codellama-ft-9/train-linux-test-others"
    info_path = f"../2.Method/data/test/others/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=True, report_file=True, language=Language.C)


def bug(only_report: bool):
    result_path = "./generality/bug/results.json"
    inspect_path = "inspect/codellama-ft/codellama-ft-9/generality/bug"
    info_path = "../2.Method/data/bug/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report, report_file=True, language=Language.C)


def java(only_report: bool):
    result_path = "./generality/java/results.json"
    inspect_path = "inspect/codellama-ft/codellama-ft-9/generality/java"
    info_path = "../2.Method/data/java/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report, report_file=True, language=Language.JAVA)


def ppathf(only_report: bool):
    result_path = f"./results/ppathf/merge.json"
    info_path = f"../2.Method/data/test/merge/info#1.json"
    inspect_path = f"inspect/ppathf/merge"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=True, language=Language.C, tool="ppathf")


def ppathf_ablation():
    result_path = "./ablation/ppathf/results.json"
    inspect_path = "inspect/codellama-ft/codellama-ft-9/ablation/ppathf"
    info_path = "../2.Method/data/test/merge/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=False, report_file=True, language=Language.C)


def ppathf_bug(only_report: bool):
    result_path = f"./results/ppathf/bug.json"
    info_path = f"../2.Method/data/bug/info#1.json"
    inspect_path = f"inspect/ppathf/bug"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=True, language=Language.C, tool="ppathf")


def ppathf_java(only_report: bool):
    result_path = "./results/ppathf/java.json"
    inspect_path = "inspect/ppathf/java"
    info_path = "../2.Method/data/java/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=True, language=Language.JAVA, tool="ppathf")


def gpt_java(only_report: bool):
    result_path = "./results/gpt/java.json"
    inspect_path = "inspect/gpt/gpt4o-java"
    info_path = "../2.Method/data/java/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.JAVA, tool="gpt-4o")


def codellama_java(only_report: bool):
    result_path = "./results/codellama/java.json"
    inspect_path = "inspect/codellama/java"
    info_path = "../2.Method/data/java/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.JAVA, tool="codellama")


def starcoder(only_report: bool):
    result_path = "./results/starcoder/results.json"
    inspect_path = "inspect/starcoder/merge"
    info_path = "../2.Method/data/test/merge/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.C, tool="starcoder")


def starcoder_java(only_report: bool):
    result_path = "./results/starcoder/java.json"
    inspect_path = "inspect/starcoder/java"
    info_path = "../2.Method/data/java/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.JAVA, tool="starcoder")


def codellama_bug(only_report: bool):
    result_path = "./results/codellama/bug.json"
    inspect_path = "inspect/codellama/bug"
    info_path = "../2.Method/data/bug/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.C, tool="codellama")


def starcoder_bug(only_report: bool):
    result_path = "./results/starcoder/bug.json"
    inspect_path = "inspect/starcoder/bug"
    info_path = "../2.Method/data/bug/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.C, tool="starcoder")


def gpt_bug(only_report: bool):
    result_path = "./results/gpt/bug.json"
    inspect_path = "inspect/gpt/gpt-3.5-turbo-bug"
    info_path = "../2.Method/data/bug/info#1.json"
    evaluate(result_path, inspect_path, info_path, only_report=only_report,
             report_file=False, language=Language.C, tool="gpt-4o")
