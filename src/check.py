import re
import subprocess
import tempfile
from enum import Enum

import Levenshtein
import yaml

import config
import format
from ast_parser import ASTParser
from common import Language
from llm import clean_llm_output


class FaultType(Enum):
    SUCCESS = "SUCCESS"
    NO_FIX = "NO_FIX"
    PLACEHOLDER = "PLACEHOLDER"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    AST_ERROR = "AST_ERROR"
    SAME_TO_DIFF = "SAME_TO_DIFF"
    SIM_DIFF = "SIM_DIFF"


class Fault:
    def __init__(self, type: FaultType, description: str | None = None, key: str | None = None):
        self.key = key
        self.type = type
        self.description = description


syntax_code_exclude = [
    "struct", "int", "new", "size_t", "size_t,", ",", ";", "->", "=", "__be16",
    "__u16", "__be32", "__u32", "__u64", "tr", "bio_size", "link_sta", "__iomem", "__asm__", "RFMT", "ret", "int,", "DECLARE_SOCKADDR(struct sockaddr_llc *, addr, msg->msg_name)", "r5conf", "=&r", "+r", "ASM_EXCEPTIONTABLE_ENTRY_EFAULT(2b"]


def clang_tidy_report(code: str) -> list[str]:
    code_file = tempfile.NamedTemporaryFile(mode='w', suffix=".c")
    report_file = tempfile.NamedTemporaryFile(mode='w', suffix=".yaml")
    code_file.write(code)
    code_file.flush()
    result = subprocess.run(
        ["clang-tidy", code_file.name, f"--export-fixes={report_file.name}", "--extra-arg=-ferror-limit=0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with open(report_file.name) as f:
        report = yaml.safe_load(f)
    error_messages = []
    if report is None:
        return error_messages
    for diag in report["Diagnostics"]:
        error_level = diag["Level"]
        if error_level != "Error":
            continue
        diag_message = diag["DiagnosticMessage"]["Message"]
        error_messages.append(diag_message)
    return error_messages


def clang_tidy_check(code: str, ignore_error_message: list[str] = []) -> Fault:
    code_file = tempfile.NamedTemporaryFile(mode='w', suffix=".c")
    report_file = tempfile.NamedTemporaryFile(mode='w', suffix=".yaml")
    code_file.write(code)
    code_file.flush()
    result = subprocess.run(
        ["clang-tidy", code_file.name, f"--export-fixes={report_file.name}", "--extra-arg=-ferror-limit=0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with open(report_file.name) as f:
        report = yaml.safe_load(f)
    if report is None:
        return Fault(FaultType.SUCCESS)
    for diag in report["Diagnostics"]:
        error_level = diag["Level"]
        if error_level != "Error":
            continue
        diag_message = diag["DiagnosticMessage"]["Message"]
        if diag_message in ignore_error_message:
            continue
        if diag_message.startswith("use of undeclared identifier"):
            matches = re.findall(r"'(.*?)'", diag_message)
            if len(matches) != 0:
                identifier = matches[0]
                if identifier.isupper():
                    continue
        elif "too many errors emitted" in diag_message:
            continue
        diag_name = diag["DiagnosticName"]
        offset = diag["DiagnosticMessage"]["FileOffset"]
        line = code[:offset].count("\n") + 1
        desp = f"There is a syntax error in line {line}: {diag_message}"
        return Fault(FaultType.SYNTAX_ERROR, desp)
    return Fault(FaultType.SUCCESS)


def checking_placeholder(target_before_sliced: str, llm_result: str) -> Fault:
    def calc_placeholder_num(code: str):
        code_lines = code.split('\n')
        placeholder_num = 0
        for line in code_lines:
            if config.PLACE_HOLDER.strip() == line.strip():
                placeholder_num += 1
        return placeholder_num
    target_placeholder_num = calc_placeholder_num(target_before_sliced)
    llm_result_placeholder_num = calc_placeholder_num(llm_result)
    if target_placeholder_num != llm_result_placeholder_num:
        return Fault(FaultType.PLACEHOLDER, "The number of placeholders is different.")
    else:
        return Fault(FaultType.SUCCESS)


def checking_ast_error(code: str) -> Fault:
    ast_parser = ASTParser(code, Language.C)
    for node in ast_parser.traverse_tree():
        assert node.text is not None
        error_line = node.start_point[0] + 1
        error_meseage = f"There is a syntax error in line {error_line}: "
        if node.is_error:
            error_code = node.text.decode().strip()
            if error_code in syntax_code_exclude or "new" in error_code:
                continue
            return Fault(FaultType.AST_ERROR, error_meseage + error_code)
        if node.is_missing:
            missing_code = ""
            if node.parent is not None:
                assert node.parent.text is not None
                missing_code = node.parent.text.decode().strip()
            return Fault(FaultType.AST_ERROR, error_meseage + missing_code)
    return Fault(FaultType.SUCCESS)


@DeprecationWarning
def checking_goto_label(llm_result: str) -> Fault:
    ast_parser = ASTParser(llm_result, Language.C)
    goto_query = """(goto_statement (statement_identifier)@label)"""
    results = ast_parser.query(goto_query)
    for result in results:
        identifier_node = result[0]
        assert identifier_node.text is not None
        identifier = identifier_node.text.decode()
        lable_query = f"""
        (labeled_statement
            label: (statement_identifier)@label
            (#eq? @label "{identifier}")
        )
        """
        result_node = ast_parser.query_oneshot(lable_query)
        if result_node is None:
            return Fault(FaultType.SYNTAX_ERROR, identifier)
    return Fault(FaultType.SUCCESS)


def checking_similarity(origin_before_sliced: str, origin_after_sliced: str, target_before_sliced: str, llm_result: str) -> Fault:
    before_is_same = format.normalize(origin_before_sliced) == format.normalize(target_before_sliced)
    after_is_same = format.normalize(origin_after_sliced) == format.normalize(llm_result)
    origin_target_before_sim = Levenshtein.ratio(format.normalize(
        origin_before_sliced), format.normalize(target_before_sliced))
    origin_target_after_sim = Levenshtein.ratio(format.normalize(
        origin_after_sliced), format.normalize(llm_result))
    origin_before_after_sim = Levenshtein.ratio(format.normalize(
        origin_before_sliced), format.normalize(origin_after_sliced))
    target_before_after_sim = Levenshtein.ratio(format.normalize(
        target_before_sliced), format.normalize(llm_result))
    if before_is_same and after_is_same:
        return Fault(FaultType.SUCCESS)
    elif before_is_same and not after_is_same:
        return Fault(FaultType.SAME_TO_DIFF)
    elif target_before_after_sim == 1:
        return Fault(FaultType.SIM_DIFF)
    elif abs(origin_target_before_sim - origin_target_after_sim) > 0.02 and abs(origin_before_after_sim - target_before_after_sim) > 0.02:
        return Fault(FaultType.SIM_DIFF)
    else:
        return Fault(FaultType.SUCCESS)


def checking(key: str, pa_s: str, pb: str, pb_s: str, px: str, px_sp: str, py_sp: str, py: str | None = None) -> Fault:
    if py is None:
        py = py_sp
    llm_result = clean_llm_output(py_sp, Language.C)

    if format.normalize(px) == format.normalize(py):
        return Fault(FaultType.NO_FIX, key=key)

    fault = checking_placeholder(px_sp, llm_result)
    if fault.type != FaultType.SUCCESS:
        fault.key = key
        return fault

    ignore_error_message = clang_tidy_report(px)
    ignore_error_message.extend(clang_tidy_report(pb))
    fault = clang_tidy_check(py, ignore_error_message)
    if fault.type != FaultType.SUCCESS:
        fault.key = key
        return fault

    fault = checking_similarity(pa_s, pb_s, px_sp, llm_result)
    if fault.type != FaultType.SUCCESS:
        fault.key = key
        return fault
    fault.key = key
    return fault


def calc_average_diff(data, info, acc):
    em_method = set(acc["em_method"])
    not_em_method = set(acc["not_em_method"])
    em_same_method = set(acc["em_same_method"])
    em_diff_method = set(acc["em_diff_method"])
    not_em_same_method = set(acc["not_em_same_method"])
    not_em_diff_method = set(acc["not_em_diff_method"])
    fault_set = set()
    fault_map = {fault.value: [] for fault in FaultType}

    diff_count = 0
    aver_diff = 0
    aver_af_diff = 0
    for key in not_em_diff_method:
        if key not in data:
            print(f"not_em_diff_method: {key}")
            continue
        llm_result = data[key]["our_tool"]
        origin_before_sliced = info[key]["pre_sliced_code"]
        origin_after_sliced = info[key]["post_sliced_code"]
        target_before_sliced = info[key]["target"]
        if format.normalize(origin_before_sliced) == format.normalize(target_before_sliced):
            continue
        diff_count += 1
        origin_target_before_sim = Levenshtein.ratio(format.normalize(
            origin_before_sliced), format.normalize(target_before_sliced))
        origin_target_after_sim = Levenshtein.ratio(format.normalize(
            origin_after_sliced), format.normalize(llm_result))
        origin_before_after_sim = Levenshtein.ratio(format.normalize(
            origin_before_sliced), format.normalize(origin_after_sliced))
        target_before_after_sim = Levenshtein.ratio(format.normalize(
            target_before_sliced), format.normalize(llm_result))
        aver_af_diff += abs(origin_before_after_sim - target_before_after_sim)
        print(
            f"origin_target_before_sim: {origin_target_before_sim}, origin_target_after_sim: {origin_target_after_sim}, {abs(origin_target_before_sim - origin_target_after_sim)}")
        aver_diff += abs(origin_target_before_sim - origin_target_after_sim)
    print(f"aver_diff: {aver_diff / diff_count}")
    print(f"aver_af_diff: {aver_af_diff / diff_count}")
